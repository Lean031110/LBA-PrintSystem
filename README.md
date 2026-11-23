# LBA PRINT SYSTEM

Sistema de impresión térmica para **Odoo 19 Community** en red local, sin nube, sin Docker y sin IoT Box. Equivalente a una "IoT Box" especializada en impresoras, con dos componentes:

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
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Guía de usuario del panel y del conector |

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

Ver [docs/PROXMOX_INSTALLATION.md](docs/PROXMOX_INSTALLATION.md) (LXC Debian 12 no privilegiado, 1 CPU/1 GB/8 GB, systemd, backup).

## Pruebas

```bash
cd server && . .venv/bin/activate && PYTHONPATH=. python -m pytest -q
cd ..
node odoo_addons/lba_print_connector/tests/test_lba_templates.mjs
```

### Estado de QA del addon Odoo

El trabajo actual está en `fix/odoo19-addon-qa-layouts`. La definición de CI
para instalación limpia y actualización con Odoo 19/PostgreSQL está añadida,
pero no se debe considerar aprobada hasta ver una ejecución real en GitHub.
El test Node del serializador no valida el patch OWL en navegador. La matriz
con resultados y pasos pendientes está en [docs/ODOO_VALIDACION.md](docs/ODOO_VALIDACION.md);
no se ha verificado instalación de Odoo, E2E/navegador ni hardware en este
entorno. No desplegar esta rama en la base real de Lo D’ Leo.

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
├── deploy/
│   ├── proxmox/            # creación del LXC
│   ├── systemd/            # servicios (API, worker, simulador)
│   └── scripts/            # install / update / backup / restore / uninstall
└── docs/                   # documentación técnica
```

## Licencia

MIT — ver [LICENSE](LICENSE). El proyecto funciona 100% en red local: sin CDNs, sin llamadas externas en operación (HTMX y CSS propios vendidos en el repo).
