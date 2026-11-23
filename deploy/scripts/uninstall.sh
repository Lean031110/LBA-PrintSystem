#!/usr/bin/env bash
# Desinstalación limpia del LBA Print Server.
# Por defecto conserva /var/lib/lba y /etc/lba-print; --purge-data borra ambos.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib_common.sh"
lba_require_root
PURGE="${1:-}"
INSTALL_DIR="${LBA_INSTALL_DIR:-/opt/lba}"
VAR_DIR="${LBA_UNINSTALL_VAR_DIR:-/var/lib/lba}"
ENV_DIR="${LBA_UNINSTALL_ENV_DIR:-/etc/lba-print}"
SYSTEMD_DIR="${LBA_SYSTEMD_DIR:-/etc/systemd/system}"
if [[ "$PURGE" != "" && "$PURGE" != "--purge-data" ]]; then
    lba_die "uso: uninstall.sh [--purge-data]"
fi

systemctl disable --now lba-print-api.service lba-print-worker.service \
    lba-print-simulator.service 2>/dev/null || true
rm -f "$SYSTEMD_DIR/lba-print-api.service" \
      "$SYSTEMD_DIR/lba-print-worker.service" \
      "$SYSTEMD_DIR/lba-print-simulator.service"
systemctl daemon-reload
rm -rf -- "$INSTALL_DIR"

if [[ "$PURGE" == "--purge-data" ]]; then
    rm -rf -- "$VAR_DIR" "$ENV_DIR"
    echo "Eliminados $INSTALL_DIR, $VAR_DIR y $ENV_DIR (incluida la BD/configuración)."
else
    echo "Conservados $VAR_DIR (BD/cola/historial) y $ENV_DIR (configuración/secretos)."
    echo "Reinstala con install.sh para recuperar el servicio con sus datos y configuración."
fi
echo "Usuario 'lba' conservado (id del sistema sin shell); elimínalo manualmente solo si ya no se necesita."
