# RELEASE — artefactos, verificación y estado de producción

Versión actual: **1.0.0** (archivo `VERSION`; addon `19.0.1.0.0`).

## 1. Artefactos de la release

Cada release publicada en GitHub adjunta estos archivos:

| Archivo | Qué es | Uso |
|---|---|---|
| `lba-print-system-1.0.0-install.tar.gz` | Paquete completo: servidor, scripts de instalación/actualización/backup/restore, unidades systemd, Docker, addon Odoo y documentación. Incluye `install.sh` en la raíz. | Instalación normal con systemd |
| `lba-print-server-debian12-amd64.tar.gz` | Servidor y scripts, mismo contenido sin el addon ni Docker. | Instalación mínima o auditoría del servidor |
| `lba_print_connector-19.0.1.0.0.zip` | Módulo Odoo 19 listo para importar (contiene `lba_print_connector/`, `INSTALL.md`, `LICENSE`, `CHANGELOG.md`, `BUILD-INFO.txt`). | Instalar en Odoo 19 Community |
| `MANIFEST.txt` | Lista completa de archivos incluidos y commit de origen. | Auditoría |
| `SHA256SUMS` | SHA-256 de todos los artefactos anteriores. | Verificación de integridad |

Imagen Docker: `ghcr.io/lean031110/lba-print-system:1.0.0` (también `sha-<12>`
y `latest` para releases estables). Ver [DOCKER.md](DOCKER.md).

Los tres paquetes se generan desde un checkout **limpio** y el mismo commit, de
forma reproducible (`BUILD-INFO.txt` identifica versión, commit y fecha de
origen). El ZIP del addon contiene código fuente Python/XML/JS: Odoo no necesita
bytecode y lo compila al cargar el módulo, por lo que «compilado» aquí significa
**paquete instalable validado en Odoo 19**, no un binario.

## 2. Verificación antes de publicar

El workflow `release.yml` solo publica si pasan estos gates sobre el commit
tageado:

1. suite del servidor (`pytest`, 62 tests);
2. suite de despliegue (`unittest`, 24 pruebas con mocks y rutas temporales);
3. tests Node del addon;
4. construcción reproducible de los tres paquetes;
5. `sha256sum -c` del conjunto;
6. construcción y publicación de la imagen Docker.

En GitHub Actions, además, la rama `main` exige los 15 checks de CI (servidor,
venv limpio del tar.gz, matriz Debian 12/13/Ubuntu 24.04/Xubuntu 24.04,
`install.sh` con systemd, estrés/concurrencia, addon Odoo 19, E2E de navegador
con impresora virtual y Docker). La evidencia consolidada está en
[FINAL_AUDIT.md](FINAL_AUDIT.md).

## 3. Instalar

- **Systemd:** descarga `lba-print-system-1.0.0-install.tar.gz`, verifica
  `sha256sum -c SHA256SUMS`, extrae y ejecuta `sudo ./install.sh`.
  Guía: [INSTALL.md](INSTALL.md).
- **Docker:** `docker pull ghcr.io/lean031110/lba-print-system:1.0.0`.
  Guía: [DOCKER.md](DOCKER.md).
- **Odoo:** instala el ZIP en una base de QA y luego en producción con respaldo.
  Guía: [INSTALL.md](INSTALL.md) §4.

## 4. Declaración de estado para producción

**LBA Print System 1.0.0 se declara listo para producción en el alcance
verificado**, entendido como:

- servidor Linux amd64 con Debian 12/13, Ubuntu 24.04 o Xubuntu 24.04 y
  Python ≥ 3.11, instalado con el paquete y systemd, o con Docker;
- red local autorizada, sin exposición directa a Internet;
- Odoo 19 Community en el mismo segmento de red;
- impresoras ESC/POS de red (raw TCP 9100) compatibles con los perfiles
  genéricos.

Lo que respalda esa declaración:

| Área | Evidencia |
|---|---|
| Instalación limpia | venv aislado desde el tar.gz + `init_db` + `import app.main` + health + worker, en CI |
| Instalación real | `install.sh` con systemd como PID 1 en Debian 12 y Ubuntu 24.04: servicios activos, healthcheck, impresión por la cola, reinicio y reinstalación idempotente |
| Distribuciones | Debian 12, Debian 13, Ubuntu 24.04 y Xubuntu 24.04 (contenedores) |
| Cola y concurrencia | 300 trabajos/3 workers/3 impresoras, 150/1/1 y ráfaga 80×16; un documento por trabajo, hashes únicos, `integrity_check=ok` |
| Odoo | instalación limpia, TransactionCase y actualización en Odoo 19 + PostgreSQL 16; E2E de navegador con trabajo `sent` y documento en la impresora virtual |
| Docker | build + smoke con API, worker, impresora virtual, reinicio y persistencia |
| Seguridad | usuario no-root en Docker, permisos 0600/0640, tokens solo-hash, allowlist, rate limit, anti-SSRF, `NoNewPrivileges`/`ProtectSystem` en systemd |
| Paquetes | reproducibles, con SHA-256 y `BUILD-INFO.txt` por commit |

## 5. Límites de la declaración

Esta declaración **no** incluye:

1. **Impresión física**: `sent` significa bytes transmitidos y aceptados por el
   socket. No se probó ninguna impresora térmica real (Rongta, Xprinter,
   Volcora). La validación con hardware está descrita en
   [COMPATIBILITY.md](COMPATIBILITY.md) §5.
2. **TLS/HTTPS y cookie `Secure`**: requiere un reverse proxy externo. La API y
   el panel deben quedar en LAN de confianza.
3. **Host real de producción**: la matriz usa contenedores; no sustituye una
   prueba en tu servidor, tu LXC ni tu red.
4. **Arquitecturas distintas de amd64** y distribuciones sin `apt-get`.
5. **Alta disponibilidad**: una base SQLite y un host; no hay clúster ni
   escalado horizontal.
6. **Odoo en versiones distintas de 19 Community** ni Odoo Enterprise/Online.
7. **Restauración ante desastres del host**: backup/restore están probados con
   mocks y rutas temporales, pero no se ensayó una pérdida total del servidor.

## 6. Proceso de release (mantenedores)

1. Actualiza `VERSION` y `CHANGELOG.md`; si cambia el addon, sube también
   `__manifest__.py`.
2. Abre PR, espera los checks verdes y fusiona a `main`.
3. Crea el tag `v1.0.0` apuntando al commit de `main` (o publica una release
   sobre ese tag).
4. `release.yml` valida la versión contra `VERSION`, ejecuta los gates, genera
   los tres paquetes + `SHA256SUMS`, publica la imagen en GHCR y adjunta todo a
   la release.
5. Verifica en la release: los cinco archivos, `sha256sum -c SHA256SUMS` y que
   la imagen aparece en GHCR con el tag esperado.

Una release con el mismo tag se actualiza con `--clobber`; nunca se reescribe un
tag ya publicado.
