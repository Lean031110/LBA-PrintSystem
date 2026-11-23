#!/usr/bin/env bash
# Actualización del LBA Print Server conservando datos/configuración.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${1:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
source "$REPO_DIR/deploy/scripts/lib_common.sh"
lba_require_root

INSTALL_DIR="${LBA_INSTALL_DIR:-/opt/lba}"
VAR_DIR="${LBA_UPDATE_VAR_DIR:-/var/lib/lba}"
ENV_FILE="${LBA_UPDATE_ENV_FILE:-/etc/lba-print/lba-print.env}"
SYSTEMD_DIR="${LBA_SYSTEMD_DIR:-/etc/systemd/system}"
APP_USER="${LBA_SERVICE_USER:-lba}"
APP_GROUP="${LBA_SERVICE_GROUP:-lba}"
PIP_CACHE_DIR="${LBA_PIP_CACHE_DIR:-/var/cache/lba-print/pip}"

export LBA_BACKUP_VAR_DIR="$VAR_DIR"
export LBA_BACKUP_ENV_DIR="${ENV_FILE%/*}"

[[ -f "$REPO_DIR/server/requirements.txt" ]] || lba_die "no se encontró un repositorio LBA válido."
[[ -d "$INSTALL_DIR/server" ]] || lba_die "no existe instalación previa en $INSTALL_DIR."

 echo "== Backup de seguridad obligatorio previo a la actualización =="
bash "$REPO_DIR/deploy/scripts/backup.sh"

 echo "== Copiar código; preservar .venv, datos y configuración =="
rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude '.pytest_cache' \
    --exclude '__pycache__' --exclude '*.pyc' --exclude 'server/data' \
    --exclude '.env*' --exclude '*.db' \
    "$REPO_DIR/" "$INSTALL_DIR/"
chown -R root:root "$INSTALL_DIR"

 echo "== Dependencias =="
install -d -m 0750 -o root -g root "$(dirname "$PIP_CACHE_DIR")" "$PIP_CACHE_DIR"
export PIP_CACHE_DIR PIP_DISABLE_PIP_VERSION_CHECK=1
PIP_INSTALL_OPTIONS=()
if [[ -n "${LBA_PIP_INDEX_URL:-}" ]]; then
    [[ "$LBA_PIP_INDEX_URL" == https://* ]] || \
        lba_die "LBA_PIP_INDEX_URL debe usar HTTPS; use LBA_PIP_WHEELHOUSE para una caché local."
    export PIP_INDEX_URL="$LBA_PIP_INDEX_URL"
fi
if [[ -n "${LBA_PIP_WHEELHOUSE:-}" ]]; then
    [[ -d "$LBA_PIP_WHEELHOUSE" && -r "$LBA_PIP_WHEELHOUSE" ]] || \
        lba_die "LBA_PIP_WHEELHOUSE debe apuntar a un directorio local legible."
    PIP_INSTALL_OPTIONS+=(--no-index --find-links "$LBA_PIP_WHEELHOUSE")
fi
lba_retry "pip update requirements" "$INSTALL_DIR/server/.venv/bin/pip" install \
    --disable-pip-version-check --retries "${LBA_PIP_RETRIES:-5}" \
    --timeout "${LBA_PIP_TIMEOUT_SECONDS:-30}" \
    "${PIP_INSTALL_OPTIONS[@]}" \
    -r "$INSTALL_DIR/server/requirements.txt"

 echo "== Permisos e inicialización compatible de SQLite =="
install -d -m 0750 -o "$APP_USER" -g "$APP_GROUP" "$VAR_DIR"
chown -R "$APP_USER:$APP_GROUP" "$VAR_DIR"
lba_run_as_user "$APP_USER" env LBA_DATA_DIR="$VAR_DIR" LBA_DB_PATH="$VAR_DIR/lba.db" \
    PYTHONPATH="$INSTALL_DIR/server" \
    "$INSTALL_DIR/server/.venv/bin/python" -c \
    'from app.database.db import init_db; init_db()'

 echo "== Actualizar unidades y reiniciar servicios =="
for unit in lba-print-api.service lba-print-worker.service lba-print-simulator.service; do
    src="$INSTALL_DIR/deploy/systemd/$unit"
    [[ -f "$src" ]] || lba_die "falta la unidad del paquete: $src"
    install -d -m 0755 -o root -g root "$SYSTEMD_DIR"
    install -m 0644 -o root -g root "$src" "$SYSTEMD_DIR/$unit"
done
systemctl daemon-reload
systemctl restart lba-print-api.service lba-print-worker.service
if systemctl is-active --quiet lba-print-simulator.service; then
    systemctl restart lba-print-simulator.service
fi
sleep 2
PORT="$(awk -F= '$1 == "LBA_PORT" { value=$2 } END { if (value != "") print value }' "$ENV_FILE" 2>/dev/null || true)"
PORT="${PORT:-8000}"
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] && (( PORT >= 1 && PORT <= 65535 )) || lba_die "LBA_PORT inválido."
curl --fail --silent --show-error "http://127.0.0.1:${PORT}/api/v1/health"
echo " → actualización OK; datos y configuración se conservaron."
