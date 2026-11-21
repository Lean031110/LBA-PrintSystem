#!/usr/bin/env bash
# ============================================================================
# LBA PRINT SYSTEM — Instalación reproducible en LXC Debian 12/Ubuntu
# (sin Docker, sin Kubernetes; venv Python; servicios systemd separados).
#
# Uso (como root dentro del contenedor LXC):
#   bash deploy/scripts/install.sh [ruta_del_repo]     # default: cwd
# ============================================================================
set -euo pipefail

REPO_DIR="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
APP_USER="lba"
APP_GROUP="lba"
INSTALL_DIR="/opt/lba"
VAR_DIR="/var/lib/lba"
ENV_DIR="/etc/lba-print"

echo "== 1) Usuario de servicio (sin shell) =="
if ! id "$APP_USER" >/dev/null 2>&1; then
    adduser --system --group --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

echo "== 2) Paquetes base =="
if command -v apt >/dev/null; then
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip rsync sqlite3 >/dev/null
fi

echo "== 3) Estructura y código =="
mkdir -p "$INSTALL_DIR" "$VAR_DIR" "$ENV_DIR"
rsync -a --delete --exclude '.git' --exclude '.venv' \
      --exclude 'server/data' "$REPO_DIR/" "$INSTALL_DIR/"
chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR"

echo "== 4) Entorno virtual =="
sudo -u "$APP_USER" python3 -m venv "$INSTALL_DIR/server/.venv"
sudo -u "$APP_USER" "$INSTALL_DIR/server/.venv/bin/pip" install -q \
    -r "$INSTALL_DIR/server/requirements.txt"

echo "== 5) Configuración de entorno =="
ENV_FILE="$ENV_DIR/lba-print.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<EOF
# LBA Print Server — configuración (systemd EnvironmentFile)
LBA_HOST=0.0.0.0
LBA_PORT=8000
LBA_DATA_DIR=$VAR_DIR
LBA_DB_PATH=$VAR_DIR/lba.db
# Secretos: genera el instalador la primera vez; cámbialos desde el panel.
# LBA_ADMIN_PASSWORD=...
# LBA_API_TOKEN=...
EOF
    chmod 640 "$ENV_FILE"
fi

echo "== 6) Inicialización de BD + credenciales iniciales =="
sudo -u "$APP_USER" env LBA_DATA_DIR="$VAR_DIR" LBA_DB_PATH="$VAR_DIR/lba.db" \
    "$INSTALL_DIR/server/.venv/bin/python" -c "
import sys; sys.path.insert(0, '$INSTALL_DIR/server')
from app.database.db import init_db
init_db()
"
if [ -f "$VAR_DIR/initial_credentials.txt" ]; then
    chmod 600 "$VAR_DIR/initial_credentials.txt"
    chown "$APP_USER:$APP_GROUP" "$VAR_DIR/initial_credentials.txt"
    echo "   ┌──────────────────────────────────────────────────┐"
    echo "   │ CREDENCIALES INICIALES en $VAR_DIR/initial_credentials.txt"
    echo "   │ Guarda el password y el token, y BORRA el archivo."
    echo "   └──────────────────────────────────────────────────┘"
fi
chown "$APP_USER:$APP_GROUP" "$VAR_DIR"

echo "== 7) Servicios systemd (API y worker separados) =="
cp deploy/systemd/lba-print-api.service /etc/systemd/system/ || \
    cp "$INSTALL_DIR/deploy/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now lba-print-api.service lba-print-worker.service

echo "== 8) Verificación =="
sleep 2
systemctl --no-pager --lines=0 status lba-print-api.service lba-print-worker.service | head -12 || true
PORT=$(grep -oP 'LBA_PORT=\K\d+' "$ENV_FILE" 2>/dev/null || echo 8000)
curl -sf "http://127.0.0.1:${PORT}/api/v1/health" && echo " → OK: LBA Print Server en marcha."

cat <<EOF

Siguientes pasos:
  1. Panel:   http://<ip-lxc>:${PORT}/   (credenciales iniciales arriba)
  2. Token:  Panel → Seguridad → crear/rotar token → pegarlo en Odoo
  3. Odoo:    instalar lba_print_connector y configurar URL/puerto/token
  4. Simulador opcional: systemctl enable --now lba-print-simulator
EOF
