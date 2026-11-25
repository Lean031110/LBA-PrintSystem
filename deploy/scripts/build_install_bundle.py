#!/usr/bin/env python3
"""Build the complete, ready-to-install LBA Print System bundle.

The bundle is reproducible from a committed revision: it contains the server,
deployment scripts, systemd units, Docker assets, Odoo addon, documentation and
a top-level ``install.sh`` wrapper so an operator can extract and install
without cloning the repository.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import re
from pathlib import Path
import subprocess
import tarfile

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_PATHS = [
    "server",
    "deploy",
    "docs",
    "docker",
    "odoo_addons",
    "VERSION",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
]
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$")

INSTALL_WRAPPER = """#!/usr/bin/env bash
# Instalación con systemd (Debian 12+/Ubuntu 24.04+, Python >= 3.11).
# Ejecutar como root desde este directorio:  sudo ./install.sh
set -euo pipefail
cd "$(dirname "$0")"
exec bash deploy/scripts/install.sh "$PWD"
"""


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def archive_sources(repo: Path, revision: str) -> list[tuple[tarfile.TarInfo, bytes | None]]:
    raw = git(repo, "archive", "--format=tar", revision, "--", *BUNDLE_PATHS)
    entries: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as source:
        for original in source.getmembers():
            data = source.extractfile(original).read() if original.isfile() else None
            entries.append((original, data))
    entries.sort(key=lambda pair: pair[0].name)
    return entries


def add_entry(out: tarfile.TarFile, original: tarfile.TarInfo, name: str,
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


def add_bytes(out: tarfile.TarFile, name: str, data: bytes, epoch: int,
              mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = epoch
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    out.addfile(info, io.BytesIO(data))


def read_addon_version(sources: list[tuple[tarfile.TarInfo, bytes | None]]) -> str:
    for original, data in sources:
        if original.name == "odoo_addons/lba_print_connector/__manifest__.py":
            assert data is not None
            match = re.search(rb'"version"\s*:\s*"([^"]+)"', data)
            if match:
                return match.group(1).decode()
    raise ValueError("no se encontró la versión del addon en el manifiesto")


def build(repo: Path, revision: str, version: str, epoch: int) -> bytes:
    sources = archive_sources(repo, revision)
    addon_version = read_addon_version(sources)
    root = f"lba-print-system-{version}"
    build_info = (
        f"LBA Print System — paquete de instalación\n"
        f"Versión: {version}\n"
        f"Commit: {revision}\n"
        f"Fecha del commit (epoch): {epoch}\n"
        f"Addon Odoo: lba_print_connector {addon_version}\n"
        f"Plataformas soportadas: Debian 12/13, Ubuntu 24.04, Xubuntu 24.04 (Python >= 3.11)\n"
    ).encode()
    readme = f"""# LBA Print System {version} — instalación

Este paquete contiene todo lo necesario para instalar LBA Print System sin
clonar el repositorio.

## Instalación con systemd (recomendada en servidor)

Requisitos: Debian 12/13 o Ubuntu/Xubuntu 24.04, Python >= 3.11, systemd, root.

```bash
sha256sum -c SHA256SUMS
tar -xzf lba-print-system-{version}-install.tar.gz
cd lba-print-system-{version}
sudo ./install.sh
```

El instalador crea el usuario `lba`, `/opt/lba`, la base en `/var/lib/lba` y
los servicios `lba-print-api` y `lba-print-worker`. Las credenciales iniciales
quedan en `/var/lib/lba/initial_credentials.txt` (modo 0600).

## Instalación con Docker

```bash
docker pull ghcr.io/lean031110/lba-print-system:{version}
docker run -d --name lba-print \\
  -p 8000:8000 \\
  -v lba-data:/data \\
  ghcr.io/lean031110/lba-print-system:{version}
```

O con `docker/docker-compose.yml` (API + worker + impresora virtual opcional).

## Addon de Odoo

El ZIP `lba_print_connector-{addon_version}.zip` se instala en Odoo 19
Community como módulo. Guía: `docs/INSTALL.md` y `odoo_addons/lba_print_connector/INSTALL.md`.

## Documentación

- `docs/INSTALL.md` — guía de instalación completa
- `docs/DOCKER.md` — imagen y compose
- `docs/RELEASE.md` — artefactos y proceso de release
- `docs/PROXMOX_INSTALLATION.md` — LXC no privilegiado
"""
    install_note = f"""LBA PRINT SYSTEM {version} — INSTALACIÓN RÁPIDA
================================================

1) Verifique el paquete:      sha256sum -c SHA256SUMS
2) Extraiga:                  tar -xzf lba-print-system-{version}-install.tar.gz
3) Instale con systemd:       cd lba-print-system-{version} && sudo ./install.sh
4) Abra el panel:             http://<ip-del-servidor>:8000/
   Credenciales:              /var/lib/lba/initial_credentials.txt
5) Addon Odoo 19:             instale lba_print_connector-{addon_version}.zip

Docker:  docker pull ghcr.io/lean031110/lba-print-system:{version}
Guía completa: docs/INSTALL.md
"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as out:
        for original, data in sources:
            if ".venv/" in original.name or "__pycache__" in original.name:
                continue
            if original.name.endswith((".pyc", ".pyo")) or original.name.startswith("server/data/"):
                continue
            add_entry(out, original, f"{root}/{original.name}", epoch, data)
        add_bytes(out, f"{root}/BUILD-INFO.txt", build_info, epoch)
        add_bytes(out, f"{root}/INSTALACION.txt", install_note.encode(), epoch)
        add_bytes(out, f"{root}/INSTALACION.md", readme.encode(), epoch)
        add_bytes(out, f"{root}/install.sh", INSTALL_WRAPPER.encode(), epoch, mode=0o755)

    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0, compresslevel=9) as gz:
        gz.write(buffer.getvalue())
    package = compressed.getvalue()

    with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as check:
        names = set(check.getnames())
        required = {
            f"{root}/install.sh",
            f"{root}/BUILD-INFO.txt",
            f"{root}/INSTALACION.md",
            f"{root}/server/requirements.txt",
            f"{root}/deploy/scripts/install.sh",
            f"{root}/deploy/systemd/lba-print-api.service",
            f"{root}/docker/Dockerfile",
            f"{root}/odoo_addons/lba_print_connector/__manifest__.py",
            f"{root}/docs/INSTALL.md",
            f"{root}/LICENSE",
        }
        missing = required - names
        if missing:
            raise ValueError(f"el paquete está incompleto: {sorted(missing)}")
        install_mode = check.getmember(f"{root}/install.sh").mode & 0o777
        if install_mode != 0o755:
            raise ValueError(f"install.sh tiene modo {install_mode:o}, se esperaba 755")
        forbidden = [name for name in names if "/.venv/" in name or name.endswith(".pyc")]
        if forbidden:
            raise ValueError(f"el paquete contiene artefactos de desarrollo: {forbidden[:3]}")
    return package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="directorio de salida fuera del checkout")
    parser.add_argument("--revision", default="HEAD", help="revisión comprometida (default: HEAD)")
    parser.add_argument("--version", default=None, help="versión (default: contenido de VERSION)")
    args = parser.parse_args()

    repo = REPO_ROOT
    revision = git(repo, "rev-parse", "--verify", f"{args.revision}^{{commit}}").decode().strip()
    status = git(repo, "status", "--porcelain", "--untracked-files=all").decode().strip()
    if status:
        raise SystemExit("se requiere un checkout limpio; no se empaquetan cambios sin commit")
    version = (args.version or (repo / "VERSION").read_text(encoding="utf-8").strip())
    if not VERSION_PATTERN.match(version):
        raise SystemExit(f"versión inválida: {version!r}")
    file_version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    if version != file_version:
        raise SystemExit(
            f"la versión solicitada ({version}) no coincide con VERSION ({file_version})"
        )
    output = Path(args.output).expanduser().resolve()
    if output == repo or repo in output.parents:
        raise SystemExit("el directorio de salida debe estar fuera del checkout Git")
    output.mkdir(parents=True, exist_ok=True)

    epoch = int(git(repo, "show", "-s", "--format=%ct", revision).decode().strip())
    package = build(repo, revision, version, epoch)
    name = f"lba-print-system-{version}-install.tar.gz"
    path = output / name
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(package)
    os.replace(temporary, path)
    print(f"{name}  {hashlib.sha256(package).hexdigest()}  ({len(package)} bytes)")
    print(f"Commit: {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
