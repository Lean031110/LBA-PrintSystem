# ARCHITECTURE — Arquitectura del sistema (Fase 0/1)

> LBA PRINT SYSTEM = **LBA Print Server** (independiente) + **LBA Print Connector** (addon Odoo 19 Community).
> Red local, sin nube, sin Docker, sin IoT Box, sin API externa de Odoo.

## 1. Diagrama general

```
┌──────────────────────────────┐         ┌──────────────────────────────────────────────┐
│  HOST ODOO (tu servidor)      │         │  PROXMOX VE                                  │
│                               │         │  ┌────────────────────────────────────────┐  │
│  Odoo 19 Community            │         │  │  LXC Debian 12 (no privilegiado)       │  │
│  ├─ point_of_sale             │  HTTP   │  │                                        │  │
│  ├─ pos_restaurant            │  JSON   │  │  LBA Print Server                      │  │
│  └─ lba_print_connector  ──────────────────►│  ├─ API FastAPI  :8000 (/api/v1)       │  │
│      (models + cola + OWL)    │ token   │  │  ├─ Panel web    (HTMX + Jinja2)       │  │
└──────────────────────────────┘         │  │  ├─ Worker (proceso systemd aparte)    │  │
                                         │  │  ├─ SQLite (WAL) data/lba.db          │  │
                                         │  │  └─ Simulator ESC/POS (opcional)     │  │
                                         │  └───────────────┬────────────────────────┘  │
                                         └──────────────────┼───────────────────────────┘
                                                            │ TCP raw 9100 (ESC/POS)
                                              ┌─────────────┼─────────────┐
                                              ▼             ▼             ▼
                                         Rongta RP326   Xprinter XP-N160II  …
                                         (Cocina)      (Bar)             (Caja)
```

- **Solo dos tramos de red**: TPV/JS → backend Odoo (RPC de sesión, nativo) y backend Odoo → LBA API (`requests` con token). El navegador del TPV **nunca** habla con LBA → se evita LNA/CORS del navegador y se evita bloquear el TPV.
- Ninguna impresora ni la API quedan expuestas a Internet (ver `SECURITY.md`).

## 2. Componentes del servidor (`server/app`)

| Paquete | Responsabilidad |
|---|---|
| `api/` | Rutas REST `/api/v1` (FastAPI, OpenAPI automática en `/docs`) |
| `core/` | Configuración (`config.py`), seguridad (hash PBKDF2, tokens, allowlist IP, rate-limit, SSRF) y utilidades |
| `database/` | Motor SQLite + `SessionLocal` + inicialización (WAL, busy_timeout) |
| `models/` | ORM SQLAlchemy: `Printer`, `Job`, `JobEvent`, `Setting`, `AuditLog` |
| `schemas/` | Contratos Pydantic (payloads de impresión con unión discriminada por `type`) |
| `services/` | `rendering` (payload→bytes ESC/POS con python-escpos `Dummy`), `discovery` (escaneo LAN autorizado), `queue` (idempotencia/estados), `preview` (reconstrucción textual de bytes) |
| `drivers/` | `simulator.py` (impresora falsa TCP para pruebas sin hardware) |
| `worker/` | Proceso independiente: reclama jobs, imprime, reintenta con backoff |
| `dashboard/` | Panel web (Jinja2 + HTMX vendorizado, sin CDN) |
| `tests/` | pytest (API, auth, idempotencia, cola, reintentos, rendering, discovery, persistencia) |

## 3. Flujo de un trabajo (end-to-end)

```
TPV (OWL)                     Odoo backend                  LBA Server                 Impresora
   │  patch printReceipt/         │                             │                          │
   │  printChanges                │                             │                          │
   ├─ rpc('/lba_print/jobs') ────►│ crea lba.print.job          │                          │
   │  (payload JSON estructurado, │ (uuid, idem_key)            │                          │
   │   idempotency_key)           ├─ requests POST /jobs ──────►│ job=pending (SQLite)     │
   │  ◄── respuesta rápida ───────┤ token+idempotencia           │                          │
   │                              │  (si LBA caído → queda en   │                          │
   │                              │   cola Odoo, cron reintenta)│                          │
   │                              │                             ├─ worker: claim ────────► │
   │                              │                             │  render→bytes ESC/POS    │
   │                              │                             ├─ socket TCP 9100 ───────►│
   │                              │                             │  job=sent (NO "printed") │
   │                              │ ◄─ GET /jobs/{id} (poll) ───┤                          │
```

1. **Payload estructurado**: Odoo manda un JSON de bloques (texto/qr/barcode/imagen/corte), nunca binarios ESC/POS.
2. **Idempotencia doble**: clave única en `lba.print.job` (Odoo) e `idempotency_key` único en SQLite (servidor). Un reintento de red no duplica el ticket.
3. **Semántica honesta**: `sent` = bytes aceptados por el socket TCP. No afirmamos impresión física (sin confirmación por hardware en v1; el estado de la impresora se consulta por accesibilidad TCP).

## 4. Máquina de estados de un trabajo (servidor)

```
             enqueue                claim (worker)         socket OK
 (idem duplicado) ─► pending ─────────────► processing ─────────────► sent
        │              │                      │                    (fin)
        │              │ cancel               │ socket error
        └─────────────► cancelled             ▼ backoff = min(5s·2^n, 300s)
                                          pending ──(attempts>=max: 5)──► failed
                                             │            ▲
                                             └── retry/reprint (API/panel) ─┘
```

- Cada transición escribe `JobEvent` (historial auditable).
- `reprint` crea un trabajo NUEVO (id distinto) con el mismo payload → histórico fiel.
- El worker procesa **una conexión por impresora a la vez** (serialización natural del socket + SQLite WAL).

## 5. Fiabilidad y persistencia

| Riesgo | Mitigación |
|---|---|
| Reinicio del LXC / servicios | SQLite en disco + jobs `pending`/`processing` huérfanos reanudados al arrancar el worker (`processing` antiguos → `pending`) |
| Escrituras concurrentes API+worker | SQLite WAL + `busy_timeout`, claim atómico por UPDATE con condición de estado |
| Impresora caída | Reintentos exponenciales (5 s → 300 s, máx. 5) + `failed` visible en panel/errores + reintento manual |
| Odoo→LBA caído | Cola `lba.print.job` en Odoo con cron (cada minuto) y reintentos controlados |
| Duplicados | `idempotency_key` único + mecanismos nativos del TPV (`nb_print`, `last_order_preparation_change`, `uiState.lastPrints`) que el connector respeta |
| Bloqueo del TPV | El TPV solo hace un RPC corto a Odoo; el POST a LBA lo hace el backend Odoo con `timeout` corto y cola de respaldo |

## 6. Panel web

- HTML/CSS/JS + **HTMX vendorizado** (cero CDN → opera sin Internet), plantillas Jinja2, tema oscuro responsive.
- Secciones: Dashboard · Dispositivos · Buscar impresoras · Configuración de dispositivos · Prueba de impresión · Cola · Historial · Errores · Configuración del servidor · Seguridad y copias de seguridad.
- Autenticación: usuario `admin` único (PBKDF2-HMAC-SHA256, 260 000 iteraciones) + cookie firmada (itsdangerous). Contraseña inicial aleatoria generada al instalar (ver `SECURITY.md`).
- Vista previa: cada trabajo `sent` guarda los bytes y una **reconstrucción textual** (parseador ESC/POS propio) → el panel muestra "lo que se envió" aunque la impresora sea remota.

## 7. Puntos de extensión Odoo (verificados, ver `RESEARCH.md` §2)

| Necesidad | Punto exacto (Odoo 19, rama 19.0) | Técnica |
|---|---|---|
| Recibo tras pago (auto/manual/bill) | `PosStore.printReceipt` — `point_of_sale/static/src/app/services/pos_store.js` L1969 | `patch(PosStore.prototype, …)` conservando `super` (fallback nativo si LBA no configurado) |
| Comanda al enviar pedido + reimpresión | `PosStore.printChanges` — mismo archivo L2255 | `patch` con `super` de respaldo |
| Deltas de modificación/cancelación | reutilizar `changesToOrder`/`getOrderChanges` + `order.updateLastOrderChange()` | no se re-implementa nada |
| Assets JS del TPV | bundle `point_of_sale._assets_pos` | clave `assets` del `__manifest__.py` |
| RPC a controlador propio | `rpc()` de `@web/core/network/rpc` → `@http.route(type='jsonrpc', auth='user')` | patrón idéntico al core (`hw_printer.js`) |
| Cron de reintento | `ir.cron` sobre `lba.print.job` | XML data (patrón `ir_cron_data.xml`) |
| Categorías→impresora LBA | `lba.print.department.category_ids` → `printer_ids`; categorías POS cargadas por `pos.session` | fuente única LBA; `pos.printer` nativo queda sin campo LBA y sigue por `super` |

**Nunca** se modifica un archivo original de Odoo: todo va en patches OWL + herencia de modelos/vistas del addon.

## 8. Decisiones de arquitectura (DADR)

1. **DADR-01**: bytes ESC/POS se generan SOLO en LBA (payload estructurado JSON). *Motivo: el requisito prohíbe que Odoo genere binarios; y el server concentra perfiles/encodings.*
2. **DADR-02**: TCP raw 9100 como único transporte v1 (Ethernet/Wi-Fi). USB/LPR/ePOS quedan fuera (documentado).
3. **DADR-03**: SQLite (no Postgres) para el server: cero dependencias externas, persistencia simple en LXC de 1 GB.
4. **DADR-04**: dos procesos systemd (API + worker) para reiniciarlos por separado y no congelar la API si el worker espera un socket.
5. **DADR-05**: `sent` ≠ `printed` en todo el sistema. Odoo distingue `pending` local, `queued` aceptado por LBA y `sent` transmitido al socket; ninguno confirma salida física.
6. **DADR-06**: sin dependencia de `/jsonrpc` ni `/json/2` de Odoo (deprecación hacia Odoo 22): el connector usa controlador propio `jsonrpc auth='user'` llamado con la sesión del TPV.
7. **DADR-07**: HTMX vendorizado → cero recursos externos en operación (requisito de operación sin Internet).
