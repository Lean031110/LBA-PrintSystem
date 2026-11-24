#!/usr/bin/env python3
"""Build reproducible, SHA-attributed server and Odoo addon packages."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import zipfile


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def commit_epoch(repo: Path, revision: str) -> int:
    return int(git(repo, "show", "-s", "--format=%ct", revision).decode().strip())


def archive_sources(repo: Path, revision: str, paths: list[str]) -> list[tuple[tarfile.TarInfo, bytes | None]]:
    raw = git(repo, "archive", "--format=tar", revision, "--", *paths)
    entries: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as source:
        for original in source.getmembers():
            data = source.extractfile(original).read() if original.isfile() else None
            entries.append((original, data))
    entries.sort(key=lambda pair: pair[0].name)
    return entries


def add_tar_entry(out: tarfile.TarFile, original: tarfile.TarInfo, name: str,
                  epoch: int, data: bytes | None) -> None:
    info = tarfile.TarInfo(name)
    info.mtime = epoch
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = original.mode & 0o777
    if original.isdir():
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        info.size = 0
        out.addfile(info)
    elif original.isfile():
        assert data is not None
        info.type = tarfile.REGTYPE
        info.size = len(data)
        out.addfile(info, io.BytesIO(data))
    elif original.issym():
        info.type = tarfile.SYMTYPE
        info.linkname = original.linkname
        info.size = 0
        out.addfile(info)
    else:
        raise ValueError(f"tipo no permitido al empaquetar: {original.name}")


def build_server_tar(repo: Path, revision: str, epoch: int, build_info: bytes) -> bytes:
    sources = archive_sources(repo, revision, ["server", "deploy", "README.md", "CHANGELOG.md", "LICENSE", "docs"])
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w", format=tarfile.PAX_FORMAT) as out:
        for original, data in sources:
            if original.name.startswith("server/.venv/") or ".pytest_cache/" in original.name:
                continue
            add_tar_entry(out, original, f"lba-print-server/{original.name}", epoch, data)
        info = tarfile.TarInfo("lba-print-server/BUILD-INFO.txt")
        info.size, info.mtime, info.mode = len(build_info), epoch, 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        out.addfile(info, io.BytesIO(build_info))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0, compresslevel=9) as gz:
        gz.write(tar_bytes.getvalue())
    package = compressed.getvalue()
    with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as check:
        names = set(check.getnames())
        required = {
            "lba-print-server/BUILD-INFO.txt",
            "lba-print-server/server/requirements.txt",
            "lba-print-server/LICENSE",
            "lba-print-server/CHANGELOG.md",
        }
        if not required.issubset(names):
            raise ValueError("el paquete servidor está incompleto")
    return package


def build_addon_zip(repo: Path, revision: str, build_info: bytes) -> bytes:
    sources = archive_sources(
        repo,
        revision,
        ["odoo_addons/lba_print_connector", "LICENSE", "CHANGELOG.md"],
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        info = zipfile.ZipInfo("BUILD-INFO.txt", date_time=(1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, build_info)
        for original, data in sources:
            if not original.isfile():
                continue
            relative = original.name.removeprefix("odoo_addons/")
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = ((0o100755 if original.mode & 0o111 else 0o100644) << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            assert data is not None
            zf.writestr(info, data)
    package = output.getvalue()
    with zipfile.ZipFile(io.BytesIO(package)) as check:
        required = {
            "lba_print_connector/__manifest__.py",
            "lba_print_connector/INSTALL.md",
            "LICENSE",
            "CHANGELOG.md",
        }
        if check.testzip() is not None or not required.issubset(check.namelist()):
            raise ValueError("el paquete Odoo está incompleto o dañado")
    return package


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="directorio de salida fuera del checkout Git")
    parser.add_argument("--revision", default="HEAD", help="revisión comprometida a empaquetar (default: HEAD)")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    revision = git(repo, "rev-parse", "--verify", f"{args.revision}^{{commit}}").decode().strip()
    status = git(repo, "status", "--porcelain", "--untracked-files=all").decode().strip()
    if status:
        raise SystemExit("se requiere un checkout limpio; no se empaquetan cambios sin commit")
    output = Path(args.output).expanduser().resolve()
    if output == repo or repo in output.parents:
        raise SystemExit("el directorio de salida debe estar fuera del checkout Git")
    output.mkdir(parents=True, exist_ok=True)

    epoch = commit_epoch(repo, revision)
    build_info = (
        f"LBA Print System QA package\nCommit: {revision}\nSource date epoch: {epoch}\n"
        "Not a production-release approval.\n"
    ).encode()
    server = build_server_tar(repo, revision, epoch, build_info)
    addon = build_addon_zip(repo, revision, build_info)
    server_name = "lba-print-server-debian12-amd64.tar.gz"
    addon_name = "lba_print_connector-19.0.1.0.0.zip"
    with tarfile.open(fileobj=io.BytesIO(server), mode="r:gz") as archive:
        server_members = sorted(archive.getnames())
    with zipfile.ZipFile(io.BytesIO(addon)) as archive:
        addon_members = sorted(archive.namelist())
    manifest = (
        f"Commit: {revision}\n"
        f"Source date epoch: {epoch}\n"
        f"Server package: {server_name}\n"
        + "".join(f"  {member}\n" for member in server_members)
        + f"Addon package: {addon_name}\n"
        + "".join(f"  {member}\n" for member in addon_members)
    ).encode()
    files = {
        server_name: server,
        addon_name: addon,
        "MANIFEST.txt": manifest,
    }
    for name, contents in files.items():
        path = output / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(contents)
        os.replace(temporary, path)
    sums = "".join(f"{sha256(contents)}  {name}\n" for name, contents in sorted(files.items()))
    sum_path = output / "SHA256SUMS"
    temporary = sum_path.with_suffix(sum_path.suffix + ".tmp")
    temporary.write_text(sums, encoding="ascii")
    os.replace(temporary, sum_path)
    print(f"Commit: {revision}")
    for name, contents in files.items():
        print(f"{name}  {sha256(contents)}  ({len(contents)} bytes)")
    print(sum_path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
