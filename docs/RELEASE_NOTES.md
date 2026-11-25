# LBA Print System 1.0.0

Primera release estable del sistema de impresión térmica ESC/POS para **Odoo 19
Community** en red local: servidor propio, cola persistente, panel web y addon
de TPV.

## Artefactos

| Archivo | Contenido |
|---|---|
| `lba-print-system-1.0.0-install.tar.gz` | Paquete completo: servidor, scripts (install/update/backup/restore/uninstall), systemd, Docker, addon Odoo y documentación. Incluye `install.sh` en la raíz. |
| `lba-print-server-debian12-amd64.tar.gz` | Servidor + scripts de despliegue. |
| `lba_print_connector-19.0.1.0.0.zip` | Módulo listo para importar en Odoo 19 Community. |
| `MANIFEST.txt` / `SHA256SUMS` | Inventario y checksums SHA-256. |

Imagen Docker: `ghcr.io/lean031110/lba-print-system:1.0.0`.

## Instalación rápida

**systemd** (Debian 12/13, Ubuntu/Xubuntu 24.04, Python ≥ 3.11):

```bash
sha256sum -c SHA256SUMS
tar -xzf lba-print-system-1.0.0-install.tar.gz
cd lba-print-system-1.0.0
sudo ./install.sh
```

**Docker**:

```bash
docker run -d --name lba-print -p 8000:8000 -v lba-data:/data \
  ghcr.io/lean031110/lba-print-system:1.0.0
```

**Odoo**: instala `lba_print_connector-19.0.1.0.0.zip` en una base de QA,
configura el servidor LBA y su token, y ejecuta «Probar conexión» y
«Sincronizar impresoras». Guías: `docs/INSTALL.md`, `docs/DOCKER.md`.

## Qué incluye

- API REST autenticada, panel HTMX, cola con reintentos/backoff y auditoría.
- Impresión ESC/POS raw TCP 9100, papel 58/80 mm, CP437/CP850/CP852/Windows-1252.
- Impresora virtual con papel en disco (`*.escpos.bin`, `*.txt`,
  `documents.jsonl`) para validar sin hardware.
- Addon Odoo 19: recibos y comandas, cola local, cron de envío, plantillas y
  diseñador de tickets.
- Instalador systemd, scripts de backup/restore/update/uninstall y LXC Proxmox.
- Imagen Docker no-root con API, worker e impresora virtual opcional.

## Verificación de esta release

El commit de la release pasó: 65 tests de servidor, 24 de despliegue, tests Node,
instalación limpia del paquete en venv aislado, paquete limpio en Debian 12/13,
Ubuntu 24.04 y Xubuntu 24.04, `install.sh` con systemd real en Debian 12 y
Ubuntu 24.04, estrés 300/3/3 + 150/1/1 + ráfaga 80×16, instalación/upgrade y
TransactionCase en Odoo 19, E2E de navegador con Odoo 19 e impresora virtual, y
build + smoke de la imagen Docker. Evidencia y límites en `docs/FINAL_AUDIT.md`.

## Límites

No se probó hardware térmico real; `sent` no implica papel impreso. No hay TLS
integrado (usa reverse proxy), solo amd64, una base SQLite y un host por
instalación. Ver `docs/RELEASE.md` §5 antes de desplegar.

Licencia MIT.
