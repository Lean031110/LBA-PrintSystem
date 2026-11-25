# LBA PRINT SYSTEM

Sistema de impresión térmica para **Odoo 19 Community** en red local, sin nube. Se limita a impresión ESC/POS de red y puede coexistir con las impresoras y periféricos nativos de Odoo; no pretende reemplazar todas las capacidades de IoT Box. Se instala con el paquete systemd o con la imagen Docker publicada. Consta de dos componentes:

| Componente | Tecnología | Qué hace |
|---|---|---|
| **LBA Print Server** | Python 3 · FastAPI · python-escpos 3.1 · SQLite · HTMX | Administra impresoras térmicas de red (ESC/POS raw TCP 9100), cola persistente con reintentos, panel web oscuro, API REST autenticada y simulador para pruebas sin hardware |
| **LBA Print Connector** | Odoo addon (Python + OWL + XML) | Conecta el TPV de Odoo 19 (recibos y comandas de `pos_restaurant`) con LBA Print Server vía RPC propio + cola de salida en Odoo |

## Documentación

| Documento | Contenido |
|---|---|
| [docs/RESEARCH.md](docs/RESEARCH.md) | Investigación Fase 0: código real Odoo 19 (rutas y líneas), python-escpos, Rongta/Xprinter, protocolos |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Arquitectura, flujos, estados, decisiones DADR |
| [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) | Matriz de compatibilidad (plataformas, impresoras, encodings) y guía de verificación con hardware |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | Contrato REST `/api/v1` con ejemplos JSON |
| [docs/ODOO_INTEGRATION.md](docs/ODOO_INTEGRATION.md) | Diseño e integración del addon Odoo |
| [docs/ODOO19_REFERENCE.md](docs/ODOO19_REFERENCE.md) | Referencias del core Odoo 19 consultadas para carga POS y puntos de extensión |
| [docs/ODOO_VALIDACION.md](docs/ODOO_VALIDACION.md) | Matriz de evidencia y checklist aislado de QA del addon |
| [docs/PRINT_TEMPLATE_DESIGNER.md](docs/PRINT_TEMPLATE_DESIGNER.md) | Contrato del diseñador visual y serialización de tickets |
| [docs/PROXMOX_INSTALLATION.md](docs/PROXMOX_INSTALLATION.md) | Instalación en LXC no privilegiado de Proxmox |
| [docs/SECURITY.md](docs/SECURITY.md) | Modelo de amenazas y mitigaciones |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Fases con objetivos y criterios de aceptación |
| [docs/FINAL_AUDIT.md](docs/FINAL_AUDIT.md) | Hallazgos, correcciones, evidencia y gates pendientes de esta auditoría |
| [docs/INSTALL.md](docs/INSTALL.md) | Instalación desde la release: paquete completo, Docker y código fuente |
| [docs/DOCKER.md](docs/DOCKER.md) | Imagen Docker, compose, variables y operación |
| [docs/RELEASE.md](docs/RELEASE.md) | Artefactos de release, verificación y declaración de producción |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Guía de usuario del panel y del conector |

## Releases e instalación

Cada release publica el **paquete completo** (`lba-print-system-<versión>-install.tar.gz`)
con todos los scripts, la **imagen Docker** (`ghcr.io/lean031110/lba-print-system`)
y el **ZIP del addon Odoo 19** listo para importar, además de `SHA256SUMS` y
`MANIFEST.txt`.

```bash
# systemd (Debian 12/13, Ubuntu/Xubuntu 24.04, Python >= 3.11)
tar -xzf lba-print-system-1.0.0-install.tar.gz
cd lba-print-system-1.0.0 && sudo ./install.sh

# Docker
docker run -d --name lba-print -p 8000:8000 -v lba-data:/data \
  ghcr.io/lean031110/lba-print-system:1.0.0
```

Guías: [INSTALL](docs/INSTALL.md) · [DOCKER](docs/DOCKER.md) · [RELEASE](docs/RELEASE.md).
La release 1.0.0 se declara lista para producción en el alcance verificado; los
límites (hardware físico, TLS, amd64, SQLite) están en [RELEASE](docs/RELEASE.md) §5.


## Arranque rápido (desarrollo, sin impresora)

```bash
cd server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# terminal 1 — simulador ESC/POS (impresora falsa en 127.0.0.1:9910)
python -m app.drivers.simulator --port 9910

# terminal 2 — API + panel
uvicorn app.main:app --port 8000

# terminal 3 — worker de la cola
python -m app.worker

# abrir http://127.0.0.1:8000  (credenciales iniciales: ver consola/instalador)
```

Primer recorrido: **Dispositivos → Añadir** (IP 127.0.0.1, puerto 9910) → **Prueba de impresión** → ver `sent` en **Cola/Historial** con vista previa del ticket.

## Instalación de producción

Desde la release (recomendado): [docs/INSTALL.md](docs/INSTALL.md).
Para un LXC no privilegiado: [docs/PROXMOX_INSTALLATION.md](docs/PROXMOX_INSTALLATION.md)
(Debian 12, 1 CPU/1 GB/8 GB, systemd, backup). Con contenedores:
[docs/DOCKER.md](docs/DOCKER.md).

## Pruebas

```bash
cd server && . .venv/bin/activate && PYTHONPATH=. python -m pytest -q
cd ..
python3 -m unittest discover -s deploy/tests -v
node --test odoo_addons/lba_print_connector/tests/*.mjs
```

### Estado de QA del addon Odoo

El código QA de esta rama fue probado en el commit
`49f7249be25e518844de6d7fb5ea427ef08ef7dc`. El
[workflow del servidor](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45285525809)
y el [workflow Odoo 19](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45285525821)
terminaron `success` sobre ese SHA. Odoo pasó instalación limpia y actualización
en bases separadas; el resumen final de cada ejecución registra 0 fallos y 0
errores en 28 tests.

Ambos workflows publicaron los paquetes QA para ese SHA. Los artefactos
descargados de los dos runs son idénticos, sus checksums SHA-256 y estructuras
ZIP/TAR se verificaron y `BUILD-INFO.txt` identifica el commit probado. Son
artefactos de QA, no una release estable ni evidencia de instalación en Debian
12/LXC.

En sandbox también pasaron 60 tests del servidor (46 warnings), 22 pruebas de
despliegue aisladas, 2 archivos Node, validación del manifest, AST Python,
parseo XML y `git diff --check`. No se han verificado navegador OWL/TPV,
integración E2E Odoo↔LBA, LXC/systemd real, estrés multiproceso, TLS/cookie
Secure, operación offline bloqueando egress ni hardware físico. La matriz de
evidencia está en [docs/ODOO_VALIDACION.md](docs/ODOO_VALIDACION.md); no instalar
esta rama ni ejecutar migraciones en la base real de Lo D’ Leo.

## Estructura

```
lba-print-system/
├── server/                 # LBA Print Server (FastAPI + escpos + cola + panel)
│   ├── app/
│   │   ├── api/            # REST /api/v1
│   │   ├── core/           # config, seguridad (tokens, PBKDF2, allowlist, rate limit)
│   │   ├── database/       # SQLite + SQLAlchemy
│   │   ├── models/         # ORM (Printer, Job, JobEvent, Setting, AuditLog)
│   │   ├── schemas/        # Pydantic (payloads de impresión)
│   │   ├── services/       # rendering ESC/POS, discovery, cola, preview
│   │   ├── drivers/        # simulador ESC/POS TCP
│   │   ├── worker/         # proceso de cola independiente
│   │   └── dashboard/      # plantillas Jinja2 + estáticos (HTMX vendorizado)
│   ├── tests/              # pytest
│   └── requirements.txt
├── odoo_addons/lba_print_connector/   # addon Odoo 19
│   ├── models/ controllers/ security/ views/ data/ tests/
│   └── static/src/{js,xml,scss}
├── docker/                 # Dockerfile, entrypoint y docker-compose
├── deploy/
│   ├── proxmox/            # creación del LXC
│   ├── systemd/            # servicios (API, worker, simulador)
│   └── scripts/            # install / update / backup / restore / uninstall / build
└── docs/                   # documentación técnica
```

## Licencia

MIT — ver [LICENSE](LICENSE). El proyecto funciona 100% en red local: sin CDNs, sin llamadas externas en operación (HTMX y CSS propios vendidos en el repo).
