#!/usr/bin/env bash
# Restauración segura de un backup LBA.
# Uso: restore.sh <fichero.db> [config.tar.gz]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib_common.sh"
lba_require_root

DB_IN="${1:?uso: restore.sh <fichero.db> [config.tar.gz]}"
CFG_IN="${2:-}"
VAR_DIR="${LBA_RESTORE_VAR_DIR:-/var/lib/lba}"
ENV_DIR="${LBA_RESTORE_ENV_DIR:-/etc/lba-print}"
STAGE_ROOT="${LBA_RESTORE_STAGE_ROOT:-$(dirname "$ENV_DIR")}"
SERVICE_USER="${LBA_SERVICE_USER:-lba}"
SERVICE_GROUP="${LBA_SERVICE_GROUP:-lba}"
DB_PATH="$VAR_DIR/lba.db"
[[ -f "$DB_IN" && -r "$DB_IN" ]] || lba_die "no se puede leer el backup SQLite: $DB_IN"
[[ -z "$CFG_IN" || ( -f "$CFG_IN" && -r "$CFG_IN" ) ]] || lba_die "no se puede leer el backup de configuración: $CFG_IN"
command -v sqlite3 >/dev/null 2>&1 || lba_die "falta sqlite3."

# Validar el snapshot antes de detener los servicios.
DB_CHECK="$(sqlite3 "$DB_IN" 'PRAGMA integrity_check;')"
[[ "$DB_CHECK" == "ok" ]] || lba_die "el backup SQLite no pasó integrity_check: $DB_CHECK"

STAGE_CFG=""
cleanup_stage_cfg() {
    [[ -z "${STAGE_CFG:-}" || ! -d "$STAGE_CFG" ]] || rm -rf -- "$STAGE_CFG"
}
trap cleanup_stage_cfg EXIT
if [[ -n "$CFG_IN" ]]; then
    python3 "$SCRIPT_DIR/validate_config_archive.py" "$CFG_IN"
    [[ ! -L "$STAGE_ROOT" ]] || lba_die "el directorio temporal de restore no puede ser un enlace simbólico."
    # mkdir -p no cambia permisos de un directorio padre ya existente (p. ej. /etc).
    # mktemp crea el subdirectorio de staging con modo privado 0700.
    mkdir -p -m 0700 -- "$STAGE_ROOT"
    STAGE_CFG="$(mktemp -d "$STAGE_ROOT/.lba-restore-config.XXXXXX")"
    tar --extract --gzip --file "$CFG_IN" --directory "$STAGE_CFG" \
        --no-same-owner --no-same-permissions
    [[ -d "$STAGE_CFG/etc/lba-print" ]] || lba_die "el tar no contiene etc/lba-print."
fi

read_port() {
    local file="$1" value=""
    if [[ -f "$file" ]]; then
        value="$(awk -F= '$1 == "LBA_PORT" { value=$2 } END { if (value != "") print value }' "$file")"
    fi
    value="${value:-8000}"
    [[ "$value" =~ ^[0-9]{1,5}$ ]] && (( value >= 1 && value <= 65535 )) || \
        lba_die "LBA_PORT inválido en configuración del restore."
    printf '%s' "$value"
}
PORT_SOURCE="$ENV_DIR/lba-print.env"
if [[ -n "$STAGE_CFG" && -f "$STAGE_CFG/etc/lba-print/lba-print.env" ]]; then
    PORT_SOURCE="$STAGE_CFG/etc/lba-print/lba-print.env"
fi
PORT="$(read_port "$PORT_SOURCE")"

# Crear un backup previo y una copia local de rollback antes de detener nada.
bash "$SCRIPT_DIR/backup.sh"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$VAR_DIR"
ROLLBACK_DB="$VAR_DIR/.lba-before-restore-$$.db"
if [[ -f "$DB_PATH" ]]; then
    sqlite3 "$DB_PATH" ".backup '$ROLLBACK_DB'"
    [[ "$(sqlite3 "$ROLLBACK_DB" 'PRAGMA integrity_check;')" == "ok" ]] || \
        lba_die "no se pudo verificar la copia de rollback de la base actual."
fi
STAGED_DB="$VAR_DIR/.lba-restore-$$.db"
install -m 0640 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$DB_IN" "$STAGED_DB"

OLD_CFG=""
DB_REPLACED=0
CFG_REPLACED=0
NEW_CFG_INSTALLED=0
RESTORE_DONE=0
rollback_restore() {
    local rc=$?
    trap - ERR INT TERM
    if (( RESTORE_DONE == 0 )); then
        systemctl stop lba-print-api.service lba-print-worker.service 2>/dev/null || true
        if (( DB_REPLACED == 1 )); then
            rm -f -- "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
            if [[ -f "$ROLLBACK_DB" ]]; then
                mv -- "$ROLLBACK_DB" "$DB_PATH"
                chown "$SERVICE_USER:$SERVICE_GROUP" "$DB_PATH"
                chmod 0640 "$DB_PATH"
            fi
        fi
        if (( CFG_REPLACED == 1 )); then
            if [[ -n "$OLD_CFG" && -d "$OLD_CFG" ]]; then
                rm -rf -- "$ENV_DIR"
                mv -- "$OLD_CFG" "$ENV_DIR"
            elif (( NEW_CFG_INSTALLED == 1 )); then
                rm -rf -- "$ENV_DIR"
            fi
        fi
        rm -f -- "$STAGED_DB"
        systemctl start lba-print-api.service lba-print-worker.service 2>/dev/null || true
        echo "Restore incompleto; se intentó restaurar el estado anterior." >&2
    fi
    [[ -n "$STAGE_CFG" && -d "$STAGE_CFG" ]] && rm -rf -- "$STAGE_CFG"
    exit "$rc"
}
trap rollback_restore ERR INT TERM

systemctl stop lba-print-api.service lba-print-worker.service
rm -f -- "$DB_PATH-wal" "$DB_PATH-shm"
DB_REPLACED=1
mv -- "$STAGED_DB" "$DB_PATH"
chown "$SERVICE_USER:$SERVICE_GROUP" "$DB_PATH"
chmod 0640 "$DB_PATH"
if [[ -n "$STAGE_CFG" ]]; then
    CFG_REPLACED=1
    if [[ -e "$ENV_DIR" ]]; then
        OLD_CFG="${ENV_DIR}.before-restore-$$"
        mv -- "$ENV_DIR" "$OLD_CFG"
    fi
    mv -- "$STAGE_CFG/etc/lba-print" "$ENV_DIR"
    NEW_CFG_INSTALLED=1
    chown -R "root:$SERVICE_GROUP" "$ENV_DIR"
    find "$ENV_DIR" -type d -exec chmod 0750 {} +
    find "$ENV_DIR" -type f -exec chmod 0640 {} +
fi
systemctl start lba-print-api.service lba-print-worker.service
sleep 2
curl --fail --silent --show-error "http://127.0.0.1:${PORT}/api/v1/health"
RESTORE_DONE=1
trap - ERR INT TERM
rm -f -- "$ROLLBACK_DB"
[[ -z "$OLD_CFG" || ! -d "$OLD_CFG" ]] || rm -rf -- "$OLD_CFG"
[[ -z "$STAGE_CFG" || ! -d "$STAGE_CFG" ]] || rm -rf -- "$STAGE_CFG"
echo " → restaurado y verificado en el puerto $PORT."
echo "La cola pendiente del backup queda disponible para el worker."
