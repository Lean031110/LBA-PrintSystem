#!/usr/bin/env bash
# Copia de seguridad consistente de LBA Print Server (SQLite + config).
# Programable: 0 3 * * *  root  bash /opt/lba/deploy/scripts/backup.sh
set -euo pipefail
VAR_DIR="/var/lib/lba"
ENV_DIR="/etc/lba-print"
OUT="/var/backups/lba"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$OUT"
echo "== Backup consistente con la API en marcha (WAL) =="
sudo -u lba sqlite3 "$VAR_DIR/lba.db" ".backup '$OUT/lba-$STAMP.db'"
[ -d "$ENV_DIR" ] && tar -czf "$OUT/lba-config-$STAMP.tar.gz" "$ENV_DIR"

echo "== Retención (últimos 14) =="
ls -1t "$OUT"/lba-*.db 2>/dev/null | tail -n +15 | xargs -r rm --
ls -1t "$OUT"/lba-config-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm --

echo "Backup: $OUT/lba-$STAMP.db (+ config)"
