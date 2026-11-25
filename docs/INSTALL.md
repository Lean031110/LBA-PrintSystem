# INSTALL — instalación desde la release

Hay tres formas de instalar LBA Print System 1.0.0. Todas usan el mismo código y
la misma base SQLite; elige según tu infraestructura.

| Vía | Cuándo usarla | Requisitos |
|---|---|---|
| **Paquete completo + `install.sh`** | Servidor físico, VM o LXC Debian/Ubuntu con systemd | Debian 12/13, Ubuntu 24.04 o Xubuntu 24.04, Python ≥ 3.11, root, systemd |
| **Docker** | Host con Docker, despliegue inmutable | Docker 24+ (amd64) |
| **Código fuente** | Desarrollo y pruebas | Python ≥ 3.11, git |

Ubuntu 22.04 **no es soportado** (Python 3.10; SQLAlchemy 2.1 y FastAPI actual
exigen ≥ 3.11). El instalador lo rechaza con un mensaje explícito.

## 1. Paquete completo (recomendado con systemd)

Descarga de la release estos dos archivos:

- `lba-print-system-1.0.0-install.tar.gz` — todo: servidor, scripts, systemd,
  Docker, addon Odoo y documentación.
- `SHA256SUMS` — checksums de todos los artefactos.

```bash
sha256sum -c SHA256SUMS
tar -xzf lba-print-system-1.0.0-install.tar.gz
cd lba-print-system-1.0.0
sudo ./install.sh
```

El instalador:

1. instala dependencias del sistema (`python3-venv`, `sqlite3`, `rsync`, `curl`);
2. crea el usuario de servicio `lba` (sin shell) y copia el código a `/opt/lba`;
3. crea el venv e instala `server/requirements.txt`;
4. escribe `/etc/lba-print/lba-print.env` (modo 0640) y `/var/lib/lba`;
5. inicializa SQLite y genera credenciales en
   `/var/lib/lba/initial_credentials.txt` (modo 0600);
6. instala y habilita `lba-print-api.service` y `lba-print-worker.service`;
7. espera hasta 60 s a que `/api/v1/health` responda.

El simulador se instala como `lba-print-simulator.service` pero queda apagado en
producción. Para pruebas sin hardware:

```bash
sudo systemctl enable --now lba-print-simulator.service
```

Panel: `http://<ip-del-servidor>:8000/` con las credenciales del archivo.
Antes de exponer el panel fuera de localhost, pon un proxy HTTPS delante.

### Actualizar, copiar y desinstalar

```bash
sudo bash deploy/scripts/backup.sh            # copia consistente de BD + config
sudo bash deploy/scripts/update.sh /ruta/al/paquete/nuevo
sudo bash deploy/scripts/restore.sh <lba.db> <lba-config-fecha.tar.gz>
sudo bash deploy/scripts/uninstall.sh         # conserva datos
sudo bash deploy/scripts/uninstall.sh --purge-data
```

`update.sh` aborta si el backup previo falla. `uninstall.sh` sin `--purge-data`
conserva `/var/lib/lba` y `/etc/lba-print`.

### Proxmox

Para un LXC no privilegiado, usa `deploy/proxmox/create_lba_ct.sh` como se
describe en [PROXMOX_INSTALLATION.md](PROXMOX_INSTALLATION.md). El contenedor
creado es Debian 12, que está en la matriz de CI.

## 2. Docker

```bash
docker pull ghcr.io/lean031110/lba-print-system:1.0.0
docker run -d --name lba-print --restart unless-stopped \
  -p 8000:8000 -v lba-data:/data \
  ghcr.io/lean031110/lba-print-system:1.0.0
```

Compose, variables, backup y límites: [DOCKER.md](DOCKER.md).

## 3. Código fuente

```bash
git clone https://github.com/Lean031110/LBA-PrintSystem.git
cd LBA-PrintSystem
python3 -m venv server/.venv
server/.venv/bin/pip install -r server/requirements.txt
cd server
LBA_DATA_DIR=./data .venv/bin/python -c 'from app.database.db import init_db; init_db()'
LBA_DATA_DIR=./data .venv/bin/uvicorn app.main:app --port 8000
```

En otra terminal: `.venv/bin/python -m app.worker` y, opcionalmente,
`.venv/bin/python -m app.drivers.simulator --port 9910 --save-dir /tmp/papel`.

## 4. Addon de Odoo 19

El ZIP `lba_print_connector-19.0.1.0.0.zip` de la release se instala en Odoo 19
Community (depende de `point_of_sale` y `pos_restaurant`):

```bash
sudo unzip lba_print_connector-19.0.1.0.0.zip -d /tmp/lba-addon
sudo cp -a /tmp/lba-addon/lba_print_connector /opt/odoo/custom-addons/
# añade /opt/odoo/custom-addons a addons_path y reinicia Odoo
```

Después: **Aplicaciones → Actualizar lista → LBA Print Connector → Instalar**.
Configura el servidor LBA y su token en **LBA Print System → Servidores** y
ejecuta «Probar conexión» y «Sincronizar impresoras». No lo instales primero en
producción: hazlo en una base descartable y con respaldo.

## 5. Verificación tras instalar

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health
sudo systemctl status lba-print-api lba-print-worker
sudo journalctl -u lba-print-api -n 50 --no-pager
```

Salud esperada: `{"status":"ok","app":"LBA Print Server","version":"1.0.0","uptime_s":…}`.
Desde el panel: **Dispositivos → Añadir** (IP y puerto 9100 de tu impresora) →
**Prueba de impresión** → estado `sent` en **Cola/Historial**.

`sent` significa que los bytes llegaron al socket de la impresora; no confirma
papel impreso. La verificación física está documentada en
[COMPATIBILITY.md](COMPATIBILITY.md) §5.

## 6. Límites conocidos

- Solo `x86_64` (paquete e imagen Docker).
- El instalador exige `apt-get` y systemd: Debian/Ubuntu. No cubre Fedora,
  RHEL ni Arch.
- No hay TLS integrado; usa un reverse proxy y no expongas la API a Internet.
- Un solo host y una sola base SQLite por instalación.
- La matriz de CI usa contenedores y systemd en contenedor; no sustituye una
  prueba en tu hardware ni con tus impresoras.
