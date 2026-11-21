# RESEARCH — Investigación técnica (Fase 0)

> Proyecto: **LBA PRINT SYSTEM** · Documento de investigación obligatoria previa a la programación.
> Fecha: 2026-11-21 · Todo lo marcado **[VERIFICADO]** se comprobó en fuente primaria en esta fase.

## 1. Método

| Tema | Fuente primaria | Método |
|---|---|---|
| Odoo 19 Community | Clon Git rama `19.0`, commit `0a722221e608f534c40c0fe33acdff010acaef53` (2026-11-10) | Clon sparse (`addons/point_of_sale`, `addons/pos_restaurant`, `addons/web`, `addons/base`, `odoo/http.py`) en `/home/z/my-project/research/odoo19` |
| python-escpos | PyPI + docs oficiales | https://pypi.org/project/python-escpos/ |
| Rongta | Web oficial del fabricante + manual oficial | https://www.rongtatech.com (catálogo y descargas) |
| Xprinter | Web oficial del fabricante | https://www.xprintertech.com |
| Odoo 19 (contexto) | Fuentes web citadas | Ver §6 |

**Regla del proyecto aplicada**: no se afirma compatibilidad de hardware sin especificaciones verificadas; lo pendiente de ver en físico queda en la matriz de `COMPATIBILITY.md`.

## 2. Odoo 19 Community — hallazgos del código real

**[VERIFICADO]** `odoo/release.py` → `version_info = (19, 0, 0, FINAL, 0, '')`, `series = "19.0"`.
**[VERIFICADO]** OWL vendido en el core: `addons/web/static/lib/owl/owl.js` → `version = "2.8.4"`.

### 2.1 Impresión de recibos en el TPV (frontend OWL)

| Hecho | Evidencia (archivo, líneas en commit citado) |
|---|---|
| El disparo de impresión tras validar pago está en `OrderPaymentValidation.afterOrderValidation()` y `canPrintReceipt` | `addons/point_of_sale/static/src/app/utils/order_payment_validation.js` L212-232 |
| La impresión central pasa por `PosStore.printReceipt({order, basic_receipt, printBillActionTriggered})` que renderiza el componente `OrderReceipt` y luego incrementa `nb_print` | `addons/point_of_sale/static/src/app/services/pos_store.js` L1969-2005 |
| La impresión física nativa requiere **IoT Box** (`HWPrinter` → `rpc(proxy/hw_proxy/default_printer_action)` con imagen JPEG rasterizada) o **Epson ePOS** (`printer_type='epson_epos'`) o fallback navegador `window.print` | `utils/printer/hw_printer.js` L19-35, `utils/printer/base_printer.js` L22-53, `services/pos_printer_service.js` |
| Reimpresión manual nativa: ReceiptScreen (`doFullPrint`/`doBasicPrint`) y TicketScreen (`onClickReprintAll` → `pos.printChanges` con `uiState.lastPrints`) | `receipt_screen.js` L35-40, `ticket_screen.js` L202-207 |
| El camarero sin `pos_hr` es `order.user_id` (campo `user_id` de `pos.order`, etiqueta "Employee"); `employee_id` solo existe si se instala `pos_hr` | `addons/point_of_sale/models/pos_order.py` L307-311; `addons/pos_hr/models/pos_order.py` L9 |
| Nombre/nº de pedido para cocina: `order.getName()` / `preparationName` (`floating_order_name || pos_reference`) | `static/src/app/models/pos_order.js` L796-809 |
| Antiduplicado nativo de recibos: `order.nb_print === 0 && pos.config.autoPrint` (`canPrintReceipt`) | `order_payment_validation.js` L212-218 |

**Conclusión**: el punto único por donde pasan recibo automático, recibo manual y bill es `PosStore.printReceipt`. Ese es el hook natural (vía `patch`) para redirigir a LBA sin sustituir el TPV.

### 2.2 Comandas (kitchen) en pos_restaurant

| Hecho | Evidencia |
|---|---|
| El modelo de impresora de comandas es **`pos.printer` y vive en `point_of_sale`** (no en pos_restaurant). Campos reales: `name`, `printer_type` (`iot`/`epson_epos`), `proxy_ip`, `product_categories_ids` (m2m a **`pos.category`** vía `printer_category_rel`), `pos_config_ids`, `epson_printer_ip`, `company_id` | `addons/point_of_sale/models/pos_printer.py` L28-62 |
| Botón "Order" → `pos.submitOrder()` → `sendOrderInPreparationUpdateLastChange` → `checkPreparationStateAndSentOrderInPreparation` (consulta al servidor `pos.order.get_preparation_change` para evitar duplicados entre dispositivos) → `sendOrderInPreparation(order, opts)` | `addons/pos_restaurant/static/src/app/services/pos_store.js` L608-618; `point_of_sale/.../pos_store.js` L2012-2053 y L2061-2125 |
| `sendOrderInPreparation` llama `changesToOrder(order, printerCategories, opts.cancelled)` y si hay cambios imprime con `printChanges(order, orderChange, reprint)`; solo tras éxito de impresión ejecuta `order.updateLastOrderChange()`; después sincroniza para que otros TPV no re-impriman | `pos_store.js` L2061-2125 |
| **Detección de modificaciones/cancelaciones**: `getOrderChanges()` compara cantidades actuales contra `order.last_order_preparation_change.lines`; produce deltas con `quantity` (positivo=nuevo, negativo=cancelado), `noteUpdate`, `uuid`, `getFullProductName()`, `attribute_value_ids` (variantes), `note`, `customer_note`, `pos_categ_id`, `group` | `static/src/app/models/utils/order_change.js` L34-171 |
| `changesToOrder()` separa `new` / `cancelled` / `noteUpdate` | `order_change.js` L1-26 |
| `printChanges(order, orderChange, reprint, printers)` filtra cada delta por `printer.config.product_categories_ids` y llama `printOrderChanges(data, printer)` → plantilla `point_of_sale.OrderChangeReceipt` | `pos_store.js` L2255-2320, L2216-2253, L2338-2343 |
| `receiptLineGrouper` es parcheable (pos_restaurant lo parchea para agrupar por "course") | `order_change.js` L173-177 + `pos_restaurant/.../utils/order_change.js` L4-11 |
| **NO EXISTEN EN 19**: `computeLineChanges`, `printingBacklog`, `print_order` (nombres de versiones ≤15; el sistema actual es `changesToOrder` + `last_order_preparation_change`) | Búsqueda global sobre point_of_sale/pos_restaurant |

### 2.3 Modelos de datos relevantes

- **`pos.category`** (NO `product.category`): `name`, `parent_id`, `child_ids`, `sequence`, `hour_until`, `hour_after`, `has_image`, `color` — `addons/point_of_sale/models/pos_category.py` L11-50.
- **`pos.config`** (impresión): `printer_ids` (m2m pos.printer), `is_order_printer`, `iface_print_via_proxy`, `iface_print_auto`, `iface_print_skip_screen`, `receipt_header`, `receipt_footer`, `basic_receipt`, `proxy_ip`, `epson_printer_ip`, `module_pos_restaurant` — `models/pos_config.py` L73-160.
- **`pos.order`**: `name`, `last_order_preparation_change` (JSON, núcleo del sistema delta), `date_order`, `user_id`, `lines`, `sequence_number`, `state` (draft/cancel/paid/done), `preset_id` (takeaway/takein/delivery; **no existe `take_away`**), `floating_order_name`, `general_customer_note`, `internal_note`, `nb_print`, `pos_reference`, `tracking_number`, `uuid` (unique), `is_edited`, `has_deleted_line`; restaurante añade `table_id`, `customer_count`, `course_ids` — `models/pos_order.py` L304-377; `pos_restaurant/models/pos_order.py` L8-10.
- **`pos.order.line`**: `product_id`, `attribute_value_ids` (m2m `product.template.attribute.value` — así llegan las **variantes**), `qty`, `full_product_name`, `customer_note`, `note` (JSON), `uuid`, `combo_*` (combos), `refunded_*` — `models/pos_order.py` L1615-1684.

### 2.4 Puntos de extensión frontend (OWL) en 19

- **[VERIFICADO]** Import oficial del patch: `import { patch } from "@web/core/utils/patch";` (`addons/web/static/src/core/utils/patch.js` L71). Sintaxis actual: `patch(Clase.prototype, { metodo() { …; super.metodo(...arguments); } })`.
- Ejemplo real de parche POS: `addons/pos_restaurant/static/src/app/services/pos_store.js` L1-21 (parchea `PosStore.prototype.setup`).
- **Bundle de assets del TPV**: `point_of_sale._assets_pos` (clave declarada en el `__manifest__.py` de point_of_sale L145-220; pos_restaurant añade su JS con esa clave, manifest L34-38). NO es `web.assets_frontend`.
- RPC del TPV: servicio `orm` (`this.orm.call`) vía `/web/dataset/call_kw` para modelos; `rpc()` de `@web/core/network/rpc` para controladores propios (patrón usado por `hw_printer.js` L20). Envoltorio de datos del POS: `this.pos.data.call(model, method, args)`.

### 2.5 Autenticación y RPC servidor Odoo 19

- **[VERIFICADO]** `route(type='json')` está **deprecado** en 19 (alias de `type='jsonrpc'`, `odoo/http.py` L812-818). Para controladores propios: `@http.route('/ruta', type='jsonrpc', auth='user')` — CSRF deshabilitado por defecto para `jsonrpc` (docstring L769-814).
- Llamadas modelo estándar: `/web/dataset/call_kw/...` con `auth="user"` por cookie de sesión (`addons/web/controllers/dataset.py` L28-32). El TPV corre con sesión de usuario → un controlador propio `jsonrpc auth='user'` es la vía correcta.
- **API externa**: `/jsonrpc`, `/xmlrpc` están en el addon `addons/rpc` **deprecados con eliminación programada en Odoo 22**; la nueva API es `/json/2` (`json2`). **Decisión de diseño**: LBA no depende de ninguna de ellas (cumple el requisito del proyecto).
- HTTP saliente: `requests` está en `requirements.txt` de Odoo 19 (L87-88) → el addon puede usar `requests.post(url, json=..., timeout=N)` con garantía de disponibilidad.
- `ir.cron`: patrón real en `odoo/addons/base/data/ir_cron_data.xml` (fields `name, model_id, state='code', code='model.metodo()', interval_number, interval_type, priority`).
- Ajustes: patrón `res.config.settings` con campos `related="pos_config_id.campo" readonly=False` (pos_restaurant L6-13) o `ir.config_parameter` (patrón `point_of_sale.use_lna`).
- **LNA (Local Network Access)**: los navegadores modernos exigen permiso LNA para que una app web (TPV) haga peticiones a IPs de la LAN (`fetch(..., {targetAddressSpace:"local"})` en `hardware_proxy_service.js` L149-153; parámetro `point_of_sale.use_lna`). **Relevante**: como LBA Print Server se invoca desde el **backend de Odoo** (Python, `requests`), no desde el navegador del TPV, este problema se evita por diseño.

### 2.6 IoT / hardware proxy (mecanismo que sustituimos)

- `point_of_sale` depende de `iot_base` (solo JS de red); **NO** del addon `iot` completo. `pos_restaurant` depende solo de `point_of_sale`.
- El POS 19 imprime por IoT mediante `HWPrinter` → `rpc("<proxy>/hw_proxy/default_printer_action")` con el recibo **rasterizado a JPEG**; el servidor del proxy (IoT Box) no está en el repo odoo/odoo.
- Epson ePOS: `EpsonPrinter` → CGI `…/cgi-bin/epos/service.cgi?devid=local_printer` (XML ePOS-Print).

**Decisión**: LBA Print Server sustituye al IoT Box para impresoras de red; el addon convierte los datos del pedido en **payload estructurado JSON** y el servidor genera los bytes ESC/POS (nunca Odoo envía binarios pre-cocinados, requisito del proyecto).

## 3. python-escpos 3.1 — [VERIFICADO]

Fuente: https://pypi.org/project/python-escpos/ (v3.1, 2023-12-17, licencia **MIT**).

- Python soportado: 3.8 → 3.12 (CPython).
- Capacidades: texto (alineación, fuentes, tamaños, negrita), **QR** (módulo `qrcode`), **códigos de barras** (módulo `python-barcode`), **imágenes/logos** (`Pillow`), **cortes** (`GS V`), reset, perfiles de capacidades.
- Perfiles: gestionados por la base de datos de perfiles **escpos-printer-db** (p. ej. `default`, `TM-T88-III`, etc.); seleccionables con `profile="..."`. Un perfil demasiado conservador puede limitar QR/HRI en clones; por eso LBA usa perfil `default` por impresora, configurable por dispositivo.
- Impresoras: `escpos.printer.Network(host, port, timeout)` para TCP, `Dummy` para capturar bytes sin hardware (clave para nuestro simulador y tests).
- Codificación: `magic_encode`/codepages — soporta cp437/cp850/cp852/… Para español, LBA deja la codepage **por impresora** (por defecto `CP850`; verificado en COMPATIBILITY.md que hay que probarla en hardware).
- **Limitación asumida y documentada**: la librería escribe en el socket; **no existe confirmación de impresión física**. LBA marca los trabajos como `sent` (enviado correctamente por TCP), nunca como "impresos", requisito del proyecto.

## 4. Impresoras objetivo

### Rongta (fabricante: Rongta Technology; web oficial https://www.rongtatech.com)

- **[VERIFICADO en manual oficial]** Manual "80MM THERMAL RECEIPT PRINTER RP325/RP326/RP327/RP328" declara: interfaz **Ethernet** y "**compatible con ESC/POS print instruction set**".
- **[VERIFICADO en catálogo oficial]** Línea 80 mm: RP325/326/327/328, RP331, RP350, RP337; línea 58 mm: RP582, RP58A, RP58E, RP58B. Todas las fichas y drivers en la sección Download oficial.
- RP326: 80 mm, 250 mm/s, USB + LAN + Serie (fuente de marketplace, coincidente con el manual).
- **Puerto TCP crudo 9100**: es el modo estándar de la interfaz Ethernet ESC/POS; verificar en físico con la guía de `COMPATIBILITY.md` §5 (DIP switches/utilidad de IP).

### Xprinter (web oficial https://www.xprintertech.com)

- **[VERIFICADO]** XP-N160II: página oficial de producto con SDK "Linux_SDK_2.0.5_ESCPOS", guía "configure IP address for Ethernet port printers", interfaces USB/Ethernet/Wi-Fi/Bluetooth (documentación específica de cada una). ESC/POS compatible. 80 mm, 160 mm/s, DIP switch de fuente/caracteres (ficha de producto y manuales de usuario en la web oficial).
- XP-N160: misma familia (predecesor). Modelos 58 mm (XP-58…) ver en matriz; puerto 9100: verificar en físico.
- Drivers oficiales para Windows/Linux/macOS/Android y OPOS → soporte de red Ethernet estándar.

**Principio aplicado**: la arquitectura de impresión es **genérica por perfil ESC/POS**; la matriz de `COMPATIBILITY.md` distingue lo verificado en especificaciones de lo que requiere comprobación con hardware físico (Rongta RP325-328 y Xprinter XP-N160II son los candidatos prioritarios de tu LAN).

## 5. Protocolos de impresión (distinguir)

| Protocolo | Transporte | Uso en ESC/POS | Decisión LBA |
|---|---|---|---|
| **TCP raw 9100** | Socket crudo al puerto 9100 (estilo JetDirect) | Estándar de facto de impresoras térmicas de red (Rongta, Xprinter, Epson TM…) | **Adoptado** (configurable) |
| **Epson ePOS-Print** | XML sobre HTTP (CGI), Epson ePOS SDK | Solo Epson ePOS; NO aplicable a clones | No soportado v1 |
| **LPR/LPD (515)** | Cola de impresión de red | Envía el trabajo al spooler; sin control de page-break/corte por documento | No soportado v1 (documentado) |
| **USB** | Bulk vendor-specific | Requiere passthrough USB al LXC (frágil) y libusb | No soportado v1 |
| **Propietarios** | Apps de fabricante | Incompatibles | No soportados |

## 6. Odoo 19 — contexto de versión

- Lanzamiento: **Odoo Experience, octubre 2025** (Bruselas) — fuente web (oec.sh FAQ y prensa del sector).
- Python: `setup.py` del clon usa `MIN_PY_VERSION` (ver valor exacto en `COMPATIBILITY.md` §1, fila "Odoo 19"); fuentes de instalación recomiendan **Python 3.11/3.12** (Ubuntu 24.04 trae 3.12). Odoo 20 exige 3.12+.
- OWL: **2.8.4** vendida en el core [VERIFICADO].
- El servidor LBA corre en su propio LXC con Python 3.12 (independiente del Python de Odoo).

## 7. Recursos para probar SIN impresora física

| Recurso | Qué aporta | URL |
|---|---|---|
| **LBA Simulator** (incluido en este repo) | Servidor TCP que emula una impresora ESC/POS raw 9100 + reconstrucción textual del ticket en el panel | `server/app/drivers/simulator.py` |
| escpos-printer-emulator | Emulador de impresora de red para desarrollo (raw TCP) | https://github.com/sangatsharma/escpos-printer-emulator |
| CrossEscPosEmulator | Emulador multiplataforma (Windows/macOS/Linux/navegador) | https://github.com/danielmeza/CrossEscPosEmulator |
| thermal-printer-simulator | Simulador nativo macOS (ESC/POS y Star, TCP) | https://github.com/mertizci/thermal-printer-simulator |
| python-escpos `Dummy` | Captura de bytes ESC/POS sin hardware (usado en nuestros tests) | docs python-escpos |

## 8. Preguntas abiertas / pendientes de hardware

1. Codepage exacta que usa el firmware de cada Rongta/Xprinter para acentos españoles (probar CP437/CP850/CP852/W-1252 con ticket de prueba).
2. Soporte real de QR y simbologías de código de barras por modelo (ticket de prueba dedicado).
3. Densidad/contraste óptimo por modelo (GS `!`/ESC `{` y comando de densidad si existe en el firmware).
4. Comportamiento ante cortes parciales vs totales (`GS V 66 n`).
5. `pos_preparation_display` (pantallas de cocina) no inspeccionado en esta fase — fuera de alcance v1.
6. Los números de línea citados corresponden al commit `0a722221…` de la rama 19.0 y pueden moverse con commits posteriores.
