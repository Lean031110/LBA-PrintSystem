#!/usr/bin/env bash
# Desinstalación limpia del LBA Print Server.
# Uso: bash uninstall.sh [--purge-data]   (sin --purge-data conserva /var/lib/lba)
set -euo pipefail
PURGE="${1:-}"

systemctl disable --now lba-print-api.service lba-print-worker.service \
    lba-print-simulator.service 2>/dev/null || true
rm -f /etc/systemd/system/lba-print-{api,worker,simulator}.service
systemctl daemon-reload

if [ "$PURGE" = "--purge-data" ]; then
    rm -rf /var/lib/lba /etc/lba-print /opt/lba
    echo "Eliminados /opt/lba, /var/lib/lba y /etc/lba-print (incluida la BD)."
else
    rm -rf /opt/lba /etc/lba-print
    echo "Conservado /var/lib/lba (BD, cola e historial). Reinstala con"
    echo "install.sh para recuperar el servicio con sus datos."
fi
echo "Usuario 'lba' conservado (id del sistema sin shell). userdel lba si quieres."
