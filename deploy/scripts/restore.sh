#!/usr/bin/env bash
# Restauración de un backup de LBA Print Server.
# Uso: bash restore.sh /var/backups/lba/lba-20260101-030000.db
set -euo pipefail
DB_IN="${1:?uso: restore.sh <fichero.db> [config.tar.gz]}"
CFG_IN="${2:-}"
VAR_DIR="/var/lib/lba"

systemctl stop lba-print-api.service lba-print-worker.service
install -m 640 -o lba -g lba "$DB_IN" "$VAR_DIR/lba.db"
rm -f "$VAR_DIR/lba.db-wal" "$VAR_DIR/lba.db-shm"
if [ -n "$CFG_IN" ] && [ -f "$CFG_IN" ]; then
    tar -xzf "$CFG_IN" -C /
fi
systemctl start lba-print-api.service lba-print-worker.service
sleep 2
curl -sf http://127.0.0.1:8000/api/v1/health && echo " → restaurado OK."
echo "La cola pendiente del backup se reanuda automáticamente (worker)."
