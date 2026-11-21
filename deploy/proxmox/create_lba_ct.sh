#!/usr/bin/env bash
# Creación del LXC NO privilegiado en Proxmox VE (ejecutar en el HOST PVE).
# Recursos: 1 vCPU · 1 GB RAM · 8 GB disco · bridge LAN (vmbr0 por defecto).
# NO instala nada en el host: solo crea el contenedor.
set -euo pipefail

CTID="${CTID:-215}"
HOSTNAME="${HOSTNAME:-lba-print}"
BRIDGE="${BRIDGE:-vmbr0}"
STORAGE="${STORAGE:-local-lvm}"
IP="${IP:-dhcp}"     # o "192.168.1.50/24,gw=192.168.1.1"
TEMPLATE="${TEMPLATE:-debian-12-standard_amd64.tar.zst}"

echo "== Plantilla Debian 12 =="
pveam update
pveam download local "$TEMPLATE" 2>/dev/null || true   # ya descargada → ok

echo "== Crear CT $CTID (unprivileged) =="
pct create "$CTID" "local:vztmpl/$TEMPLATE" \
  --hostname "$HOSTNAME" \
  --unprivileged 1 \
  --cores 1 --memory 1024 --swap 512 \
  --rootfs "${STORAGE}:8" \
  --net0 "name=eth0,bridge=${BRIDGE},ip=${IP}" \
  --onboot 1 \
  --features nesting=1 \
  --start 1

echo
echo "LXC creado y arrancado. Siguientes pasos (docs/PROXMOX_INSTALLATION.md):"
echo "  pct enter $CTID"
echo "  apt update && apt install -y python3 python3-venv python3-pip git rsync sqlite3"
echo "  # subir el repo (git clone … o rsync) y:"
echo "  bash deploy/scripts/install.sh"
echo
echo "Firewall del host (si aplica): permite 8000/tcp desde la LAN a este CT;"
echo "NUNCA expongas el 8000 a Internet (ver docs/SECURITY.md)."
