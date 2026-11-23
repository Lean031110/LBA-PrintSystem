# ROADMAP — Fases, objetivos y criterios de aceptación

> Regla del encargo nº 11: antes de cada fase se documentan objetivos y criterios de aceptación; al terminar, archivos creados, pruebas y pendientes (eso se registra en `CHANGELOG.md`).

## Auditoría de estabilización — 2026-11-23 (QA con CI, no release)

El commit de código QA `49f7249be25e518844de6d7fb5ea427ef08ef7dc` pasó los dos workflows de GitHub: servidor [45285525809](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45285525809) y Odoo 19 [45285525821](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45285525821). El gate servidor pasó pytest, deploy, Node, smoke con simulador y empaquetado; el gate Odoo pasó instalación limpia, 28 TransactionCase, actualización en una segunda base, otros 28 TransactionCase y empaquetado. Los ZIP/TAR de ambos workflows se descargaron, sus checksums pasaron y los builds coincidieron byte a byte.

La suite local reejecutada pasó **60 tests del servidor** (46 warnings), **22 pruebas de despliegue** aisladas y **2 archivos Node**; también pasaron AST Python, manifest, parseo XML y `git diff --check`. Eso no valida OWL/TPV en navegador, integración E2E Odoo→LBA→simulador, LXC/systemd real, estrés multiproceso, TLS/cookie Secure, operación offline bloqueando egress ni impresión física. Se registró en `FINAL_AUDIT.md` la evidencia y el límite de recuento observado en los logs Odoo.

**No declarar versión estable ni integrar en `main`** mientras falten los gates de navegador/TPV, E2E, despliegue Debian 12/LXC con systemd, estrés multiproceso, TLS/cookie, offline, validación física autorizada y revisión de seguridad/compatibilidad completa. La identidad de plantillas Proxmox locales, dependencias con lock/hash, matriz de plataformas, renderer `profile`/`density` y workflow de release estable también siguen pendientes. No se desplegó producción.

## Fase 0 — Investigación obligatoria ✅ HECHA

**Objetivos**: inspeccionar Odoo 19 real, python-escpos, impresoras y protocolos; producir los 8 documentos.
**Criterios de aceptación**: (1) clon de la rama 19.0 inspeccionado con rutas/líneas citadas; (2) cero afirmación de compatibilidad de hardware sin fuente; (3) docs en `docs/`.
**Resultado**: `RESEARCH.md`, `ARCHITECTURE.md`, `COMPATIBILITY.md`, `API_CONTRACT.md`, `ODOO_INTEGRATION.md`, `PROXMOX_INSTALLATION.md`, `SECURITY.md`, este ROADMAP.
**Pendientes**: verificación física de Rongta/Xprinter (guía en COMPATIBILITY §5); `pos_preparation_display` fuera de alcance.

## Fase 1 — Estructura del proyecto ✅ HECHA

**Objetivos**: monorepo + rama `feature/lba-print-foundation`.
**Criterios**: estructura `server/` + `odoo_addons/lba_print_connector/` + `deploy/` + `docs/`; LICENSE MIT; README; `.gitignore` sin secretos; primer commit en rama independiente.
**Pendientes**: push a GitHub al final de la sesión (regla de no publicar antes de tests).

## Fase 2 — Servidor de impresión 🚧 EN CURSO (núcleo terminado esta sesión)

**Objetivos**: registro manual y descubrimiento LAN; perfiles 58/80 mm; encoding ES; tickets con texto/QR/barcode/logo/corte; cola; reintentos; estados; persistencia; panel completo; **simulador**.
**Criterios de aceptación**:
1. Alta de impresora por IP/puerto con validación anti-SSRF.
2. `POST /printers/discover` encuentra un puerto 9100 abierto en rango autorizado (probado contra el simulador).
3. Ticket de prueba con acentos español renderizado (bytes contienen la codepage elegida) y enviado a la impresora (simulador) → estado `sent`.
4. Reinicio del worker → trabajos `pending` sobreviven (SQLite).
5. Panel: 10 secciones navegando, login admin, vista previa textual del último ticket.
6. Tests pytest verdes (ver Fase 8).

## Fase 3 — API /api/v1 🚧 EN CURSO (contrato ya implementado esta sesión)

**Objetivos**: 12 endpoints + autenticación + límites + OpenAPI.
**Criterios**: 401 sin token; 403 desde IP no autorizada; 409 idempotencia duplicada; `429` al superar rate limit; `/docs` sirve OpenAPI.
**Pendiente**: —.

## Fase 4 — Complemento Odoo 🚧 EN CURSO (estructura + núcleo esta sesión)

**Objetivos**: `lba_print_connector` completo (models, security, views, data, controllers, OWL) con cola de salida.
**Criterios**:
1. Módulo instalable en Odoo 19 Community (manifest + access + menús).
2. Config servidor (URL/puerto/token/estado/probar/sincronizar) operativa.
3. Departamentos Caja/Cocina/Pizzería/Bar/Salón cargados + custom.
4. Recibo tras pago y comanda al "Order" con parches en `printReceipt`/`printChanges` (super preservado).
5. Deltas de modificación/cancelación via `orderChange` del core.
6. Cola `lba.print.job` + cron; TPV nunca bloqueado > 3 s (timeout corto + cola).
7. Reimpresión manual cubierta (mismos hooks).
8. Tests con mocks + guía de validación en instancia local del usuario.
**Pendiente**: validación en vivo sobre tu Odoo local (checklist en `tests/`).

## Fase 5 — Colas y fiabilidad ✅ NÚCLEO HECHO

UUID jobs · idempotencia (doble capa) · SQLite persistente · worker independiente · serialización por impresora · backoff exponencial 5 s→300 s · máx. 5 · `failed`/`retry`/`reprint` · recuperación tras reinicio (`processing` huérfanos → `pending`).

## Fase 6 — Seguridad ✅ HECHO (ver `SECURITY.md`)

Token Bearer · allowlist IP · rate limit · PBKDF2 · SSRF bloqueado (169.254.169.254, 100.64/10, públicas) · validación Pydantic · auditoría · LXC no privilegiado · sin credenciales en código.

## Fase 7 — Instalación Proxmox ✅ HECHO (scripts + docs)

LXC Debian 12 unprivileged 1c/1GB/8GB bridge LAN · venv · systemd separados (API/worker/simulador) · `install.sh`/`update.sh`/`backup.sh`/`restore.sh`/`uninstall.sh` · nada en el host · sin Docker.

## Fase 8 — Pruebas ✅ SUITE pytest DEL SERVIDOR EN VERDE; addon con tests de mock

API · DB · cola · reintentos · idempotencia · autenticación · enrutamiento/estados · formato de tickets (bytes ESC/POS) · errores de conexión (puerto cerrado) · **simulador ESC/POS** incluido · guía de verificación Rongta/Xprinter (COMPATIBILITY §5) + guía de validación Odoo.
**Pendiente**: badge CI en verde en GitHub (workflow incluido), pruebas sobre hardware real.

## Fase 9 — Entrega ✅ ESTA SESIÓN

Servidor funcional · panel · API documentada (OpenAPI + `API_CONTRACT.md`) · addon instalable · instalador LXC · systemd · pruebas · docs técnicas · **guía de usuario** (`USER_GUIDE.md`) · matriz de compatibilidad · `CHANGELOG.md` detallado · repo GitHub `LBA-PrintSystem` (público, MIT) rama `feature/lba-print-foundation`.

## Próximos hitos (post-fundación)

1. **V1.1**: confirmación física de impresión (DLE EOT `1B 04 1?`) y estado real por impresora → `sent` vs `printed`.
2. **V1.2**: corte parcial/total por dispositivo + densidad por firmware (GS `!` / ESC `{`).
3. **V1.3**: multipapel (talonarios), logo por departamento con plantilla de subida en el panel.
4. **V1.4**: métricas por impresora (tickets/día, errores) y exportación CSV.
5. **V1.5**: HTTPS interno en LAN + ban temporal por IP.
6. **V2.0**: pantallas de cocina (evaluar `pos_preparation_display`) y multi-servidor LBA por tienda.
