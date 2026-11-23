# CHANGELOG — Historial detallado de cambios

Formato: por fase, con objetivos → entregables → pruebas → pendientes.
Rama de trabajo actual: `fix/odoo19-addon-qa-layouts`; la fundación `feature/lba-print-foundation` no se modificó.

## Continuación de auditoría/estabilización — 2026-11-23 (QA local, sin release)

- En la rama `fix/odoo19-addon-qa-layouts`, sobre HEAD base `7ae0857d6ae9cf50f4d1c6470fe54171527e34ed`, se reparó el staging de restore para no cambiar `/etc` y normalizar permisos; backup rechaza symlinks/hardlinks; ACL y guard ORM bloquean creación POS directa incluso para responsables y solo managers/admin editan rutas de departamentos; el controlador eleva tras validar sesión/configuración; 409 remoto exige ID y estado conocido; health consulta SQLite; reimpresión de impresora archivada se rechaza; idempotencia resuelve errores de concurrencia SQLite; claim y evento se confirman juntos; walkthrough usa temporales privados y limpieza por defecto.
- Evidencia local reejecutada: servidor **60 passed, 46 warnings**; despliegue **22 passed** con rutas temporales/mocks (incluye casos Proxmox simulados); Node **2 archivos passed**. Bash `-n` validó **8 scripts**, compileall/AST Python **55 archivos**, parseo XML **11 archivos**, PyYAML **2 workflows** y `git diff --check` pasó. Las pruebas no equivalen a Proxmox real, LXC, runtime Odoo, navegador ni hardware.
- GitHub: [CI servidor 45239085620](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45239085620) y [CI Odoo 45239085651](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45239085651) terminaron `success` en el SHA base `7ae0857...`; no ejecutan cambios locales. El workflow Odoo local fija upstream `62c2f793058de87ff453532f206a96a1e71845d2`, pero requiere una nueva ejecución para validarlo.
- El empaquetador se construyó dos veces para el SHA base antes de estos cambios locales, con salidas reproducibles. No se generaron paquetes actuales, no se descargó/verificó artefacto final y no se publica release.
- El builder QA se amplió para exigir `LICENSE`/`CHANGELOG.md` en ambos artefactos e incluir `INSTALL.md` dentro del ZIP Odoo; el build final limpio de esta revisión y su verificación SHA aún están pendientes.
- Pendientes: CI del nuevo SHA y TransactionCase de las nuevas regresiones Odoo, instalación LXC Debian 12/systemd, navegador OWL/TPV, E2E Odoo↔LBA, stress multiproceso, HTTPS y cookie `Secure`, offline, hashes del paquete final, renderer `profile`/`density`, verificación hash de plantilla Proxmox/CT preexistente, validación física autorizada. No se desplegó producción, no se accedió a la BD de Lo D’ Leo, no se escaneó la LAN ni se enviaron comandos a hardware.

## Auditoría y QA del addon — 2026-11-23 (rama de trabajo)

- Se agregó CI de instalación limpia y actualización de `lba_print_connector` sobre Odoo 19.0/PostgreSQL 16. El run final [45237021879](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45237021879), SHA `d3c99b323c78af9b1bedcfa4f635391e44a3d0fe`, pasó la instalación, los TransactionCase y la actualización del addon en una segunda base aislada. Los logs registran 22 tests y 0 fallos/errores tanto en instalación como en upgrade.
- El run del servidor [45237021802](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45237021802), en el mismo SHA, pasó **44 tests** y el smoke end-to-end de API, cola, rendering, simulador, worker y panel.
- La secuencia de QA corrigió: XML del manifest ignorados por `**/data/`; una vista de búsqueda incompatible con el RNG de Odoo 19; fixtures de TransactionCase con nombres repetidos; y un helper que reemplazaba `blocks=[]` por un payload válido. También se corrigió el límite de bloques del diseñador y se retiró `tracking` no soportado por el modelo.
- Los logs de Odoo contienen dos sentencias SQL con nivel `ERROR` por cada ejecución: son las violaciones de unicidad intencionales de tests, atrapadas dentro de savepoints. Los resúmenes de instalación y actualización confirman 0 tests fallidos y 0 errores. GitHub también anota que las acciones actuales de Node 20 son forzadas a Node 24; es un aviso de mantenimiento, no un fallo del run.
- El enrutamiento POS LBA usa departamentos/categorías como fuente de verdad, conserva `super` de las impresoras nativas, omite deltas vacíos y carga los modelos/datos de plantillas necesarios para el POS. La cola conserva `pending` local, `queued` aceptado por LBA y `sent` transmitido al socket, sin afirmar salida física.
- Evidencia adicional local: test Node pasó; `compileall` y sintaxis Python de tests pasaron; 11 XML parsearon y el `search_view` pasó el RNG oficial de Odoo 19; YAML parseado; `git diff --check` pasó antes de documentar. La suite final del servidor fue ejecutada por CI (44/44); esta continuación no ejecutó TransactionCase en un Odoo local.
- Siguen pendientes navegador/OWL, flujo real TPV, integración E2E Odoo↔LBA, carrera de varios workers en una prueba concurrente y hardware. No se instaló ni modificó producción.

### Fuera de alcance verificado

No se instaló ni modificó la base de producción de Lo D’ Leo. La impresora Volcora no se ha identificado ni probado; solo se conoce por reporte del usuario como térmica Wi-Fi para cocina. No se hicieron escaneos LAN ni se enviaron comandos a hardware.

## [0.1.0] — 2026-11-21 — FUNDACIÓN (Fases 0–9 núcleo)

### Fase 0 — Investigación obligatoria ✅
**Hecho**
- Clon real `odoo/odoo` rama `19.0` @ `0a722221e608f534c40c0fe33acdff010acaef53`
  (sparse: point_of_sale, pos_restaurant, web, base) → hallazgos con
  archivo/línea en `docs/RESEARCH.md` (pos.printer en point_of_sale,
  printReceipt L1969, printChanges L2255, getOrderChanges/changesToOrder,
  patch de `@web/core/utils/patch`, bundle `point_of_sale._assets_pos`,
  `type='jsonrpc'` con CSRF off, /jsonrpc+/json/2 deprecados→no usados,
  `requests` en requirements.txt de Odoo 19, LNA).
- python-escpos 3.1 verificado en PyPI (MIT, py3.8–3.12); sonda práctica de
  codepages (CP850: á=0xa0, é=0x82, ñ=0xa4, ¿=0xa8, ¡=0xad) y de barcode
  por hardware (EAN13/EAN8/CODE39 OK; CODE128→fallback software).
- Rongta (manual oficial RP325/326/327/328: Ethernet + ESC/POS) y Xprinter
  XP-N160II (web oficial: Ethernet/WiFi/BT + SDK ESC/POS) verificados en
  fuentes primarias; emuladores comunitarios localizados.
**Docs**: RESEARCH · ARCHITECTURE · COMPATIBILITY · API_CONTRACT ·
ODOO_INTEGRATION · PROXMOX_INSTALLATION · SECURITY · ROADMAP (+9 más tarde).
**Pendiente**: verificación física Rongta/Xprinter (guía COMPATIBILITY §5).

### Fase 1 — Estructura ✅
Monorepo `server/` · `odoo_addons/lba_print_connector/` · `deploy/` ·
`docs/` · README · LICENSE MIT · `.gitignore` (cero secretos) · rama
`feature/lba-print-foundation` (nada fuera de ella).

### Fase 2 — Servidor de impresión ✅
- **API FastAPI + panel HTMX/Jinja2 oscuro responsive**: 10 secciones
  (Dashboard, Dispositivos, Buscar, Configuración dispositivo, Prueba,
  Cola, Historial, Errores, Configuración, Seguridad y copias).
- **Login admin** PBKDF2-HMAC-SHA256 (260 000 iter.) + cookie firmada.
- **Alta manual** de impresoras (IP/puerto validados anti-SSRF) y
  **discovery** de rango LAN autorizado (asyncio, connect-only, ≤1024 hosts).
- **Papel 58/80mm** (32/48 columnas), encodings ES (CP437/CP850/CP852/W-1252
  + AUTO), alineación/negrita/tamaños/densidad/corte por dispositivo.
- **Motor ESC/POS** (python-escpos `Dummy` → bytes): texto, QR, barcode
  (EAN13/EAN8/UPC/CODE39/ITF/CODE128-fallback-software), imagen/logo
  base64, feed/corte; ticket de prueba con 4 variantes.
- **Simulador ESC/POS** (TCP raw) + **vista previa** reconstruida de los
  bytes en el panel (visible para cualquier impresora).
- HTMX vendorizado (sin CDN/Internet en operación).
- Bug encontrado y corregido durante la fase: magic-encode conmutaba a
  W-1252 ante caracteres fuera de la codepage fija → ahora la codificación
  fija se anuncia con `ESC t n` y se codifica por línea con `errors='replace'`.

### Fase 3 — API /api/v1 ✅
12+ endpoints (`/health`, `/stats`, printers CRUD+discover+test,
jobs create/list/detail/retry/reprint/cancel, purge) con OpenAPI en `/docs`.
Auth: token Bearer (hash SHA-256 en BD, prefijo identificable), **allowlist
de IP** por CIDR, rate limit 120/min, **SSRF bloqueado** (públicas,
169.254.169.254, 100.64/10, test-nets), validación Pydantic estricta.

### Fase 4 — Complemento Odoo `lba_print_connector` (estado actualizado por auditoría)
- Manifest 19.0.1.0.0 (deps `point_of_sale`+`pos_restaurant`; MIT;
  assets → `point_of_sale._assets_pos`).
- Modelos de servidor/impresora/departamento, plantillas/bloques y cola local persistente; instalación limpia y actualización verificadas por CI aislado en Odoo 19/PostgreSQL 16 (run `45237021879`). Esto no significa que se haya instalado en la instancia real del usuario.
- El enrutamiento LBA proviene de `lba.print.department.category_ids` y `printer_ids`; no existe el campo `pos.printer.lba_printer_id`. Las impresoras nativas continúan mediante `super`.
- `/lba_print/jobs` persiste el trabajo y no hace HTTP remoto inmediato. El cron procesa fuera del camino del POS; `pending`, `queued` y `sent` tienen semánticas distintas.
- Los TransactionCase pasaron en CI bajo Odoo 19. El test Node solo valida serialización/claves y no prueba OWL.
- Guía y evidencia vigente: `docs/ODOO_INTEGRATION.md` y `docs/ODOO_VALIDACION.md`.

### Fase 5 — Colas y fiabilidad ✅
En el servidor LBA, la cola mantiene backoff y persistencia; el CI final pasó 44 tests y smoke end-to-end con simulador. En Odoo, el addon y el cron pasaron TransactionCase en PostgreSQL; el mecanismo `FOR UPDATE SKIP LOCKED` aún requiere una prueba de estrés con varios workers concurrentes para verificar ausencia de doble reclamo bajo carrera real.

### Fase 6 — Seguridad ✅
Implementada por diseño en cada capa (ver `docs/SECURITY.md`): tokens
aleatorios solo-hash, allowlist IP, rate limit login/api, PBKDF2, SSRF,
validación de payloads, auditoría persistente, LXC unprivileged,
`NoNewPrivileges/ProtectSystem` en systemd, cero credenciales en repo.

### Fase 7 — Instalación Proxmox ✅
`create_lba_ct.sh` (CT unprivileged Debian 12, 1c/1GB/8GB, bridge LAN),
`install.sh` (usuario `lba` sin shell, venv, BD, credenciales 1-vez,
systemd **api/worker/simulator separados**), `update.sh`, `backup.sh`
(sqlite .backup consistente), `restore.sh`, `uninstall.sh`. Nada en el host;
sin Docker.

### Fase 8 — Pruebas ✅
**44 tests pytest en verde** (API, auth/token/IP/allowlist/rate-limit,
printers CRUD+SSRF+discovery, idempotencia, payloads inválidos, rendering
ES/QR/barcode/corte/58mm, worker end-to-end con simulador TCP real,
reintentos/backoff/failed, retry manual, recuperación tras reinicio, claim
sin duplicados, persistencia SQLite/WAL, purga retención, panel login/
secciones/alta/prueba). + **Simulador ESC/POS** incluido y **demo
reproducible** (`deploy/scripts/demo_walkthrough.sh`, ejecutada con éxito:
estado `sent`, 302 bytes, vista previa correcta, 409 idempotencia, 10
secciones 200). + Tests Odoo con mocks. CI GitHub Actions incluida.
**Pendiente**: badge CI en GitHub, verificación física Rongta/Xprinter.

### Fase 9 — Entrega ✅ (esta sesión)
Servidor funcional · panel · API documentada (OpenAPI + API_CONTRACT) · addon instalado/actualizado en CI aislado Odoo 19 (sin despliegue en producción) · instalador LXC + scripts · systemd · pruebas · docs
técnicas · guía de usuario · matriz de compatibilidad · este CHANGELOG ·
repo público GitHub `LBA-PrintSystem` (MIT) · zip descargable.

## Pendientes globales (ROADMAP v1.1+)
1. Confirmación física de impresión (DLE EOT) → `sent` vs `printed` real.
2. Validación en instancia Odoo 19 real del usuario (checklist listo).
3. Corte parcial/total y densidad por firmware (con hardware).
4. HTTPS interno en LAN, ban temporal por IP, métricas/export CSV.
5. Evaluación `pos_preparation_display` (pantallas de cocina).
