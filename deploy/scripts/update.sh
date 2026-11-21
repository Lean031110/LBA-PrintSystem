#!/usr/bin/env bash
# Actualización del LBA Print Server (código + dependencias + servicios).
set -euo pipefail
REPO_DIR="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
INSTALL_DIR="/opt/lba"
VAR_DIR="/var/lib/lba"

echo "== Backup de seguridad previo =="
bash "$(dirname "$0")/backup.sh" || true

echo "== Copiar código nuevo =="
rsync -a --delete --exclude '.git' --exclude '.venv' --exclude 'server/data' \
      "$REPO_DIR/" "$INSTALL_DIR/"
chown -R lba:lba "$INSTALL_DIR"

echo "== Dependencias =="
sudo -u lba "$INSTALL_DIR/server/.venv/bin/pip" install -q \
    -r "$INSTALL_DIR/server/requirements.txt"

echo "== Migración (create_all idempotente) =="
sudo -u lba env LBA_DATA_DIR="$VAR_DIR" LBA_DB_PATH="$VAR_DIR/lba.db" \
    "$INSTALL_DIR/server/.venv/bin/python" -c "
import sys; sys.path.insert(0, '$INSTALL_DIR/server')
from app.database.db import init_db
init_db()
"

echo "== Reinicio de servicios =="
systemctl restart lba-print-api.service lba-print-worker.service
sleep 2
PORT=$(grep -oP 'LBA_PORT=\K\d+' /etc/lba-print/lba-print.env 2>/dev/null || echo 8000)
curl -sf "http://127.0.0.1:${PORT}/api/v1/health" && echo " → actualización OK."
echo "La cola pendiente se conserva (SQLite) y el worker la reanuda solo."
