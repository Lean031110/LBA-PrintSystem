#!/usr/bin/env bash
# ============================================================================
# LBA PRINT SYSTEM — Instalación en LXC Debian 12/Ubuntu con systemd.
# Uso como root: bash deploy/scripts/install.sh [ruta_del_repo]
# Las rutas de mirrors opcionales conservan verificación TLS/GPG:
#   LBA_APT_SOURCE_LIST=/ruta/a/sources.list
#   LBA_PIP_INDEX_URL=https://mirror.example/simple
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib_common.sh"
lba_require_root

REPO_DIR="${1:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
APP_USER="lba"
APP_GROUP="lba"
INSTALL_DIR="/opt/lba"
VAR_DIR="/var/lib/lba"
ENV_DIR="/etc/lba-print"
SYSTEMD_DIR="/etc/systemd/system"
LOG_FILE="/var/log/lba-print/install.log"
APT_CACHE_DIR="/var/cache/apt/archives"
PIP_CACHE_DIR="/var/cache/lba-print/pip"
APT_RETRIES="${LBA_APT_RETRIES:-3}"
APT_TIMEOUT="${LBA_APT_TIMEOUT_SECONDS:-30}"
PIP_TIMEOUT="${LBA_PIP_TIMEOUT_SECONDS:-30}"

[[ -d "$REPO_DIR/server" && -f "$REPO_DIR/server/requirements.txt" ]] || \
    lba_die "no se encontró un repositorio LBA válido en $REPO_DIR."
for protected_path in "$INSTALL_DIR" "$VAR_DIR" "$ENV_DIR" "$SYSTEMD_DIR"; do
    [[ ! -L "$protected_path" ]] || lba_die "ruta de instalación protegida no puede ser enlace: $protected_path"
done

umask 077
install -d -m 0750 "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
chmod 0600 "$LOG_FILE"
# El log y las credenciales se protegen con chmod explícito. El resto del árbol
# (/opt/lba, venv incluido) debe ser legible/ejecutable por el usuario lba que
# corre los servicios, así que no se propaga el umask restrictivo.
umask 022
exec > >(tee -a "$LOG_FILE") 2>&1

echo "== LBA Print System: instalación =="
echo "Repositorio: $REPO_DIR"
echo "Log protegido: $LOG_FILE"

command -v apt-get >/dev/null 2>&1 || lba_die "este instalador requiere Debian/Ubuntu con apt-get."
command -v rsync >/dev/null 2>&1 || echo "rsync se instalará como dependencia base."

APT_OPTIONS=(
    -o "Acquire::Retries=$APT_RETRIES"
    -o "Acquire::http::Timeout=$APT_TIMEOUT"
    -o "Acquire::https::Timeout=$APT_TIMEOUT"
    -o "Dir::Cache::archives=$APT_CACHE_DIR"
)
if [[ -n "${LBA_APT_SOURCE_LIST:-}" ]]; then
    [[ -r "$LBA_APT_SOURCE_LIST" ]] || lba_die "LBA_APT_SOURCE_LIST no es legible."
    APT_OPTIONS+=(
        -o "Dir::Etc::sourcelist=$LBA_APT_SOURCE_LIST"
        -o "Dir::Etc::sourceparts="
    )
    echo "Se usará la lista APT configurada por el administrador (verificación de firmas APT activa)."
fi

install -d -m 0755 -o root -g root "$APT_CACHE_DIR"
install -d -m 0750 -o root -g root "$(dirname "$PIP_CACHE_DIR")" "$PIP_CACHE_DIR"

echo "== 1) Actualizar índices y dependencias del sistema con reintentos =="
lba_retry "apt-get update" apt-get "${APT_OPTIONS[@]}" update -qq
lba_retry "apt-get install" apt-get "${APT_OPTIONS[@]}" install -y -qq --no-install-recommends \
    adduser ca-certificates curl python3 python3-venv python3-pip rsync sqlite3 util-linux

if ! id "$APP_USER" >/dev/null 2>&1; then
    adduser --system --group --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$APP_USER"
else
    getent group "$APP_GROUP" >/dev/null 2>&1 || groupadd --system "$APP_GROUP"
    usermod --gid "$APP_GROUP" "$APP_USER"
fi
id "$APP_USER" >/dev/null 2>&1 || lba_die "no se pudo crear el usuario de servicio $APP_USER."

 echo "== 2) Copiar código preservando fuera de Git datos/configuración =="
install -d -m 0755 -o root -g root "$INSTALL_DIR"
rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude '.pytest_cache' \
    --exclude '__pycache__' --exclude '*.pyc' --exclude 'server/data' \
    --exclude '.env*' --exclude '*.db' \
    "$REPO_DIR/" "$INSTALL_DIR/"
# El proceso de impresión no puede modificar el código que ejecuta.
chown -R root:root "$INSTALL_DIR"

 echo "== 3) Entorno Python y dependencias (caché persistente/reintentos) =="
python3 -m venv "$INSTALL_DIR/server/.venv"
# SQLAlchemy 2.1 y FastAPI actual exigen Python >= 3.11. Debian 12 y
# Ubuntu 24.04 ya lo traen; Ubuntu 22.04 (3.10) no es soportado.
if ! "$INSTALL_DIR/server/.venv/bin/python" -c \
        'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    lba_die "se requiere Python >= 3.11 (Debian 12+/Ubuntu 24.04+); esta imagen trae $("$INSTALL_DIR/server/.venv/bin/python" -V 2>&1)."
fi
export PIP_CACHE_DIR PIP_DISABLE_PIP_VERSION_CHECK=1
PIP_INSTALL_OPTIONS=()
if [[ -n "${LBA_PIP_INDEX_URL:-}" ]]; then
    [[ "$LBA_PIP_INDEX_URL" == https://* ]] || \
        lba_die "LBA_PIP_INDEX_URL debe usar HTTPS; use LBA_PIP_WHEELHOUSE para una caché local."
    export PIP_INDEX_URL="$LBA_PIP_INDEX_URL"
    echo "Se usará el índice PIP configurado por el administrador; TLS del cliente sigue activo."
fi
if [[ -n "${LBA_PIP_WHEELHOUSE:-}" ]]; then
    [[ -d "$LBA_PIP_WHEELHOUSE" && -r "$LBA_PIP_WHEELHOUSE" ]] || \
        lba_die "LBA_PIP_WHEELHOUSE debe apuntar a un directorio local legible."
    PIP_INSTALL_OPTIONS+=(--no-index --find-links "$LBA_PIP_WHEELHOUSE")
fi
lba_retry "pip install requirements" "$INSTALL_DIR/server/.venv/bin/pip" install \
    --disable-pip-version-check --retries "${LBA_PIP_RETRIES:-5}" \
    --timeout "$PIP_TIMEOUT" "${PIP_INSTALL_OPTIONS[@]}" \
    -r "$INSTALL_DIR/server/requirements.txt"
chown -R root:root "$INSTALL_DIR"

 echo "== 4) Configuración persistente =="
install -d -m 0750 -o lba -g lba "$VAR_DIR"
chown -R lba:lba "$VAR_DIR"
install -d -m 0750 -o root -g lba "$ENV_DIR"
ENV_FILE="$ENV_DIR/lba-print.env"
if [[ -L "$ENV_FILE" ]]; then
    lba_die "$ENV_FILE no puede ser un enlace simbólico."
fi
if [[ ! -f "$ENV_FILE" ]]; then
    cat > "$ENV_FILE" <<EOF
# LBA Print Server — configuración (systemd EnvironmentFile)
LBA_HOST=0.0.0.0
LBA_PORT=8000
LBA_SIM_PORT=9910
LBA_DATA_DIR=$VAR_DIR
LBA_DB_PATH=$VAR_DIR/lba.db
# Los secretos se generan de forma aleatoria al inicializar la BD.
EOF
fi
chown root:lba "$ENV_FILE"
chmod 0640 "$ENV_FILE"

 echo "== 5) Inicialización SQLite como usuario de servicio =="
lba_run_as_user "$APP_USER" env LBA_DATA_DIR="$VAR_DIR" LBA_DB_PATH="$VAR_DIR/lba.db" \
    PYTHONPATH="$INSTALL_DIR/server" \
    "$INSTALL_DIR/server/.venv/bin/python" -c \
    'from app.database.db import init_db; init_db()'
if [[ -f "$VAR_DIR/initial_credentials.txt" ]]; then
    chmod 0600 "$VAR_DIR/initial_credentials.txt"
    chown "$APP_USER:$APP_GROUP" "$VAR_DIR/initial_credentials.txt"
    echo "Credenciales iniciales generadas; consulta y protege $VAR_DIR/initial_credentials.txt."
fi

 echo "== 6) Instalar explícitamente las tres unidades systemd =="
install -d -m 0755 -o root -g root "$SYSTEMD_DIR"
for unit in lba-print-api.service lba-print-worker.service lba-print-simulator.service; do
    src="$INSTALL_DIR/deploy/systemd/$unit"
    [[ -f "$src" ]] || lba_die "falta la unidad requerida en el paquete: $src"
    install -m 0644 -o root -g root "$src" "$SYSTEMD_DIR/$unit"
done
systemctl daemon-reload
systemctl enable --now lba-print-api.service lba-print-worker.service
# El simulador se instala, pero queda apagado en producción salvo habilitación explícita.

 echo "== 7) Verificación del servicio =="
PORT="$(awk -F= '$1 == "LBA_PORT" { value=$2 } END { if (value != "") print value }' "$ENV_FILE")"
PORT="${PORT:-8000}"
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] && (( PORT >= 1 && PORT <= 65535 )) || lba_die "LBA_PORT inválido en $ENV_FILE."
systemctl --no-pager --lines=0 status lba-print-api.service lba-print-worker.service | head -12 || true
# El primer arranque importa la app y crea el esquema: esperar readiness
# acotada en lugar de asumir que 2 s bastan en cualquier hardware.
HEALTH_OK=0
for _ in $(seq 1 60); do
    if curl --fail --silent --show-error "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null; then
        HEALTH_OK=1
        break
    fi
    sleep 1
done
(( HEALTH_OK == 1 )) || lba_die "la API no respondió /api/v1/health en 60 s (journalctl -u lba-print-api)."
curl --fail --silent --show-error "http://127.0.0.1:${PORT}/api/v1/health"
echo " → LBA Print Server responde en el puerto $PORT."

cat <<EOF

Siguientes pasos:
  1. Panel: http://<ip-lxc>:${PORT}/ (credenciales en $VAR_DIR/initial_credentials.txt)
  2. Configurar un proxy HTTPS de LAN antes de usar el panel fuera de localhost.
  3. Simulador opcional: systemctl enable --now lba-print-simulator.service
  4. Los mirrors configurables deben usar TLS y, para APT, fuentes con firma válida.
EOF
