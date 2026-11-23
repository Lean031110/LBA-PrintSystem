# PROXMOX_INSTALLATION — Instalación en LXC (Fase 7)

> Objetivo: contenedor **no privilegiado** Debian 12 en Proxmox VE, sin Docker ni Kubernetes, con servicios systemd separados para API y worker. **Nunca se instala nada en el host Proxmox.**

## 1. Crear el contenedor

GUI (Datacenter → local → CT Templates → "Turnkey"? no: plantilla Debian 12 estándar) o CLI:

```bash
# 1) Descargar plantilla (en el host Proxmox)
pveam update && pveam download local debian-12-standard_amd64.tar.zst

# 2) Crear CT NO privilegiado (recursos: 1 core / 1 GB / 8 GB)
pct create 215 local:vztmpl/debian-12-standard_amd64.tar.zst \
  --hostname lba-print \
  --unprivileged 1 \
  --cores 1 --memory 1024 --swap 512 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --onboot 1 \
  --features nesting=1 \
  --start 1
# ( bridge=vmbr0 = tu bridge LAN; para IP fija:
#   ip=192.168.1.50/24,gw=192.168.1.1 )

# 3) Entrar y crear usuario de servicio
pct enter 215
adduser --system --group --home /opt/lba --shell /usr/sbin/nologin lba
```

Alternativa reproducible: `deploy/proxmox/create_lba_ct.sh` (mismo procedimiento con controles).

El script reutiliza un archivo de plantilla local ya presente y evita volver a descargarlo; **no valida su identidad por hash criptográfico**. Antes de usar una plantilla preexistente, el operador debe verificar origen y checksum por un canal confiable. No interpretar “presente/local” como “verificada”.

## 2. Instalar el servidor (dentro del CT)

```bash
apt update && apt install -y python3 python3-venv python3-pip git rsync
# subir el repo (git clone … o rsync) a /opt/lba
/opt/lba/deploy/scripts/install.sh   # hace TODO lo siguiente:
#   1. venv en /opt/lba/server/.venv
#   2. pip install -r server/requirements.txt
#   3. inicializa BD en /var/lib/lba/lba.db y llave secreta
#   4. genera contraseña admin + token API inicial (solo se muestran 1 vez)
#   5. instala y habilita lba-print-api.service y lba-print-worker.service
```

Servicios (`deploy/systemd/`): separados por diseño (DADR-04) — la API nunca se congela por una impresora lenta.

- `lba-print-api.service` → `uvicorn app.main:app --host 0.0.0.0 --port 8000` (User=lba)
- `lba-print-worker.service` → `python -m app.worker` (User=lba)
- opcional demo: `lba-print-simulator.service`

## 3. Red y firewall (LAN only)

- El CT solo necesita reachability a: Odoo (entrante 8000/tcp) y a las impresoras (saliente 9100/tcp).
- En el host Proxmox (fuera del CT) o en el firewall de la LAN, bloquear acceso exterior al 8000. El propio servidor además aplica allowlist de IPs por configuración (`SECURITY.md`).
- No se abre ningún puerto a Internet; no se instala agente cloud.

## 4. Actualizar / desinstalar / copia de seguridad

| Operación | Script | Qué hace |
|---|---|---|
| Actualizar | `deploy/scripts/update.sh` | `git pull` (o rsync del código), `pip install -r requirements.txt`, migración `init_db` idempotente, `systemctl restart lba-print-{api,worker}` |
| Backup | `deploy/scripts/backup.sh` | Copia SQLite consistente `.db`, archivo de configuración separado `lba-config-*.tar.gz` (si existe) y `*.sha256`; directorio/archivos root-only. Rechaza symlinks/hardlinks de configuración para mantener compatibilidad con el validador de restore. Retiene 14 conjuntos. No crea un tar combinado. |
| Restaurar | `deploy/scripts/restore.sh <db> [config.tar.gz]` | Valida integridad/configuración, usa staging privado sin cambiar permisos del padre existente, normaliza directorios a 0750/archivos a 0640, reemplaza con rollback ante fallos y comprueba readiness SQLite/HTTP en el puerto restaurado. Ejecutar solo en una instancia controlada. |
| Desinstalar | `deploy/scripts/uninstall.sh` | Detiene servicios y elimina código/unidades; conserva datos y configuración por defecto. `--purge-data` elimina ambos explícitamente. |

Las pruebas automatizadas de scripts usan temporales, `sudo` y mocks; no equivalen a una instalación/restauración en Debian 12/LXC con systemd real. No desplegar esta rama en producción hasta superar ese gate.

## 5. Criterios de aceptación de la instalación

1. `systemctl status lba-print-api lba-print-worker` → activos y `Restart=always`.
2. `curl http://<lba-ip>:8000/api/v1/health` → `{"status":"ok"}` sin token.
3. Panel accesible desde la LAN con la contraseña generada; login incorrecto rechazado.
4. Tras `pct reboot`: ambos servicios suben solos y la cola pendiente se reanuda (persistencia).
5. `sqlite3 /var/lib/lba/lba.db "PRAGMA journal_mode;"` → `wal`.
