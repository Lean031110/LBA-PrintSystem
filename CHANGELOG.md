# CHANGELOG — Historial detallado de cambios

Formato: por fase, con objetivos → entregables → pruebas → pendientes
(regla 12 del encargo). Repo: `LBA-PrintSystem`, rama `feature/lba-print-foundation`.

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

### Fase 4 — Complemento Odoo `lba_print_connector` ✅ (validación en instancia real pendiente)
- Manifest 19.0.1.0.0 (deps `point_of_sale`+`pos_restaurant`; MIT;
  assets → `point_of_sale._assets_pos`).
- Models: `lba.print.server` (URL/puerto/token/estado + **Probar conexión**/
  **Sincronizar impresoras**), `lba.print.printer` (réplica sincronizada),
  `lba.print.department` (Caja/Cocina/Pizzería/Bar/Salón precargados +
  custom; m2m impresoras + **pos.category**), `lba.print.job` (**cola de
  salida persistente** con uuid + idempotency_key únicos, estados,
  reintentos, cron 1 min + refresco 5 min).
- Herencias sin tocar el core: `pos.printer.lba_printer_id`,
  `pos.config.lba_active/lba_receipt_printer_id` (+`_load_pos_data_fields`).
- Controller `/lba_print/jobs` (`type='jsonrpc'`, `auth='user'`, patrón del
  core) con envío inmediato (timeout corto) y cola de respaldo.
- **OWL**: `patch(PosStore.prototype.printReceipt)` y `printChanges` con
  `super` de respaldo; deltas nativos (`generateOrderChange`) → payload
  estructurado; semántica `nb_print`/`lastPrints` replicada; notificaciones
  no bloqueantes; errores → cola Odoo.
- Security: ACLs por grupo + reglas multi-compañía + token solo `group_system`.
- Tests Odoo (mocks de requests): servidor/sincronización, cola completa,
  idempotencia, payloads, departamentos. **Guía de validación** en
  `docs/ODOO_VALIDACION.md` (12 pasos + CI).

### Fase 5 — Colas y fiabilidad ✅
Claim atómico (`UPDATE … WHERE status='pending'`) + `db.refresh` tras claim
(bug de identity-map detectado por tests y corregido); serialización natural
por impresora; backoff 5s→300s; máx. 5; `retry`/`reprint`/`cancel`;
recuperación de huérfanos al reiniciar; SQLite WAL; eventos auditables.

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
Servidor funcional · panel · API documentada (OpenAPI + API_CONTRACT) ·
addon instalable · instalador LXC + scripts · systemd · pruebas · 10 docs
técnicas · guía de usuario · matriz de compatibilidad · este CHANGELOG ·
repo público GitHub `LBA-PrintSystem` (MIT) · zip descargable.

## Pendientes globales (ROADMAP v1.1+)
1. Confirmación física de impresión (DLE EOT) → `sent` vs `printed` real.
2. Validación en instancia Odoo 19 real del usuario (checklist listo).
3. Corte parcial/total y densidad por firmware (con hardware).
4. HTTPS interno en LAN, ban temporal por IP, métricas/export CSV.
5. Evaluación `pos_preparation_display` (pantallas de cocina).
