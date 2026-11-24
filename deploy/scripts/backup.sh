#!/usr/bin/env bash
# Copia consistente SQLite + configuración sensible de LBA Print Server.
# Programable como root: 0 3 * * * root /opt/lba/deploy/scripts/backup.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib_common.sh"
lba_require_root

VAR_DIR="${LBA_BACKUP_VAR_DIR:-/var/lib/lba}"
ENV_DIR="${LBA_BACKUP_ENV_DIR:-/etc/lba-print}"
OUT="${LBA_BACKUP_DIR:-/var/backups/lba}"
DB_PATH="$VAR_DIR/lba.db"
[[ ! -L "$VAR_DIR" && ! -L "$ENV_DIR" ]] || lba_die "la ruta de datos/configuración no puede ser un enlace simbólico."
[[ -f "$DB_PATH" ]] || lba_die "no existe la base de datos $DB_PATH."
command -v sqlite3 >/dev/null 2>&1 || lba_die "falta sqlite3."

umask 077
[[ ! -L "$OUT" ]] || lba_die "el directorio de backups no puede ser un enlace simbólico."
install -d -m 0700 -o root -g root "$OUT"
chmod 0700 "$OUT"
chown root:root "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
DB_NAME="lba-$STAMP.db"
CFG_NAME="lba-config-$STAMP.tar.gz"
SUM_NAME="lba-$STAMP.sha256"
TMP_DIR="$(mktemp -d "$OUT/.lba-backup.XXXXXX")"
cleanup() {
    if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]]; then
        rm -rf -- "$TMP_DIR"
    fi
}
trap cleanup EXIT

printf '%s\n' '== Backup consistente SQLite (incluye WAL) =='
sqlite3 "$DB_PATH" ".backup '$TMP_DIR/$DB_NAME'"
[[ -s "$TMP_DIR/$DB_NAME" ]] || lba_die "SQLite no generó la copia."
DB_CHECK="$(sqlite3 "$TMP_DIR/$DB_NAME" 'PRAGMA integrity_check;')"
[[ "$DB_CHECK" == "ok" ]] || lba_die "integrity_check del backup falló: $DB_CHECK"

if [[ -d "$ENV_DIR" ]]; then
    [[ ! -L "$ENV_DIR" ]] || lba_die "$ENV_DIR no puede ser un enlace simbólico."
    mkdir -p "$TMP_DIR/root/etc"
    cp -a -- "$ENV_DIR" "$TMP_DIR/root/etc/lba-print"
    if find "$TMP_DIR/root/etc/lba-print" -mindepth 1 \
        \( -type l -o \( -type f -links +1 \) \) -print -quit | grep -q .; then
        lba_die "la configuración contiene symlinks o hardlinks; no se puede crear un backup restaurable."
    fi
    tar -czf "$TMP_DIR/$CFG_NAME" -C "$TMP_DIR/root" etc/lba-print
    rm -rf -- "$TMP_DIR/root"
fi
(
    cd "$TMP_DIR"
    if [[ -f "$CFG_NAME" ]]; then
        sha256sum "$DB_NAME" "$CFG_NAME" > "$SUM_NAME"
    else
        sha256sum "$DB_NAME" > "$SUM_NAME"
    fi
)
chmod 0600 "$TMP_DIR"/*
chown root:root "$TMP_DIR"/*

mv -- "$TMP_DIR/$DB_NAME" "$OUT/$DB_NAME"
if [[ -f "$TMP_DIR/$CFG_NAME" ]]; then
    mv -- "$TMP_DIR/$CFG_NAME" "$OUT/$CFG_NAME"
fi
mv -- "$TMP_DIR/$SUM_NAME" "$OUT/$SUM_NAME"
rmdir "$TMP_DIR"
TMP_DIR=""

# Retener los últimos 14 conjuntos de base de datos y sus archivos asociados.
mapfile -t OLD_DBS < <(find "$OUT" -maxdepth 1 -type f -name 'lba-*.db' -printf '%f\n' | sort -r | tail -n +15)
for old_db in "${OLD_DBS[@]}"; do
    old_stamp="${old_db#lba-}"
    old_stamp="${old_stamp%.db}"
    rm -f -- "$OUT/$old_db" "$OUT/lba-config-$old_stamp.tar.gz" "$OUT/lba-$old_stamp.sha256"
done

echo "Backup verificado: $OUT/$DB_NAME"
if [[ -f "$OUT/$CFG_NAME" ]]; then
    echo "Configuración: $OUT/$CFG_NAME"
fi
echo "SHA-256: $OUT/$SUM_NAME"
