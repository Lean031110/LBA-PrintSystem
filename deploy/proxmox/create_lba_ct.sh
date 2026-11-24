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
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"

for command_name in pveam pvesm pct; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "ERROR: falta el comando Proxmox requerido: $command_name (ejecutar en el host PVE)." >&2
    exit 2
  }
done
[[ "$CTID" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: CTID debe ser un entero positivo." >&2; exit 2; }

# Fallar con un diagnóstico no destructivo en vez de intentar crear o modificar
# un contenedor preexistente con identidad potencialmente distinta.
if pct config "$CTID" >/dev/null 2>&1; then
  echo "ERROR: CTID $CTID ya existe; no se modificó. Elija otro CTID o revise el CT existente manualmente." >&2
  exit 2
fi

echo "== Plantilla Debian 12 =="
TEMPLATE_VOLID="${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}"
TEMPLATE_PATH="$(pvesm path "$TEMPLATE_VOLID" 2>/dev/null || true)"
if [[ -n "$TEMPLATE_PATH" && -f "$TEMPLATE_PATH" ]]; then
  echo "Usando plantilla local existente: $TEMPLATE_VOLID"
else
  pveam update
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
  TEMPLATE_PATH="$(pvesm path "$TEMPLATE_VOLID")"
  [[ -n "$TEMPLATE_PATH" && -f "$TEMPLATE_PATH" ]] || {
    echo "ERROR: la plantilla no aparece en el almacenamiento tras la descarga: $TEMPLATE_VOLID" >&2
    exit 1
  }
fi

echo "== Crear CT $CTID (unprivileged) =="
pct create "$CTID" "$TEMPLATE_VOLID" \
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
