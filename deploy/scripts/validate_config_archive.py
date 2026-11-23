#!/usr/bin/env python3
"""Validate an LBA configuration backup before root extracts it."""
from __future__ import annotations

import sys
import tarfile
from pathlib import PurePosixPath

MAX_MEMBERS = 4096
MAX_TOTAL_FILE_BYTES = 64 * 1024 * 1024
ROOT = "etc/lba-print"


def validate_config_archive(archive: str) -> None:
    try:
        with tarfile.open(archive, "r:gz") as tf:
            members = tf.getmembers()
            if len(members) > MAX_MEMBERS:
                raise ValueError(f"demasiados miembros en backup ({len(members)})")

            entries: dict[str, tarfile.TarInfo] = {}
            total_size = 0
            for member in members:
                original = member.name
                if original.startswith("/"):
                    raise ValueError(f"miembro inseguro en backup: {original}")

                name = original
                while name.startswith("./"):
                    name = name[2:]
                if ".." in name.split("/"):
                    raise ValueError(f"miembro inseguro en backup: {original}")

                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError(f"miembro inseguro en backup: {original}")
                normalized = str(path)
                if normalized in entries:
                    raise ValueError(f"miembro duplicado en backup: {original}")
                if not (normalized == ROOT or normalized.startswith(ROOT + "/")):
                    raise ValueError(f"ruta no permitida en backup de configuración: {original}")
                if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                    raise ValueError(f"tipo de archivo no permitido en backup: {original}")
                if member.isfile():
                    total_size += member.size
                    if total_size > MAX_TOTAL_FILE_BYTES:
                        raise ValueError(
                            f"el contenido del backup supera el límite de {MAX_TOTAL_FILE_BYTES} bytes"
                        )
                entries[normalized] = member

            for name, member in entries.items():
                parent = PurePosixPath(name).parent
                while str(parent) != ".":
                    parent_name = str(parent)
                    parent_entry = entries.get(parent_name)
                    if parent_entry is not None and not parent_entry.isdir():
                        raise ValueError(f"un archivo se usa como directorio: {parent_name}")
                    parent = parent.parent
    except (OSError, tarfile.TarError) as exc:
        raise ValueError(f"no se pudo leer el backup de configuración: {exc}") from exc


def main() -> int:
    if len(sys.argv) != 2:
        print("uso: validate_config_archive.py ARCHIVO.tar.gz", file=sys.stderr)
        return 2
    try:
        validate_config_archive(sys.argv[1])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
