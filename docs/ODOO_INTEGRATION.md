# ODOO_INTEGRATION — LBA Print Connector para Odoo 19 Community (Fase 4)

> Módulo: `odoo_addons/lba_print_connector` · depende de `point_of_sale` + `pos_restaurant`.
> No usa IoT Box, no usa la API externa (`/jsonrpc`, `/json/2`), no modifica archivos del core: todo por herencia de modelos/vistas y `patch` OWL oficial (`@web/core/utils/patch`).

## 1. Instalación

```bash
# en el host Odoo (ej. /opt/odoo/custom-addons)
cp -r odoo_addons/lba_print_connector /opt/odoo/custom-addons/
chown -R odoo: /opt/odoo/custom-addons/lba_print_connector
# reiniciar servicio Odoo y, en Ajustes → Aplicaciones, instalar "LBA Print Connector"
```

Requisitos verificados: Odoo 19 Community (rama 19.0), `point_of_sale` y `pos_restaurant` instalados.

## 2. Modelos (todos propios, prefijo `lba.print.`)

| Modelo | Campos clave | Función |
|---|---|---|
| `lba.print.server` | `name`, `base_url`, `port` (8000), `api_token`, `active`, `state`, `last_check`, `last_message` | Configuración del servidor LBA. Botones: **Probar conexión** (`GET /health`) y **Sincronizar impresoras** (`GET /printers`) |
| `lba.print.printer` | `server_id`, `external_id`, `name`, `manufacturer`, `model`, `ip`, `port`, `paper_width_mm`, `protocol`, `status`, `active` | Réplica de las impresoras del servidor (sincronizada; modificable desde el servidor) |
| `lba.print.department` | `name`, `code`, `printer_ids` (m2m), `category_ids` (m2m `pos.category`), `active` | Departamentos: **Caja, Cocina, Pizzería, Bar, Salón** cargados por data XML (`noupdate`); se pueden añadir personalizados |
| `lba.print.job` | `uuid`, `department_id`, `printer_id`, `order_ref`, `order_uuid`, `kind` (receipt/kitchen/delta/reprint), `payload_json`, `state` (pending/sent/failed/cancelled), `attempts`, `max_attempts`, `next_attempt`, `last_error`, `external_job_id` | **Cola de salida persistente en Odoo** para cuando LBA no responda |

Herencias (sin tocar el core):

- `pos.printer` += `lba_printer_id` (m2o `lba.print.printer`): cada impresora de comanda nativa del TPV se mapea a una impresora LBA (las categorías siguen decidiéndose con el campo nativo `product_categories_ids` — verificado en `RESEARCH.md` §2.2).
- `pos.config` += `lba_receipt_printer_id` (m2o) + `lba_active` (bool): impresora de recibos de caja.

## 3. Flujo técnico (ver `RESEARCH.md` §2 para las líneas exactas del core)

1. **Recibo tras pago** — `patch(PosStore.prototype, { printReceipt() })` (`point_of_sale/.../services/pos_store.js` L1969): si `pos.config.lba_active` y hay impresora de recibo asignada → construye payload estructurado (encabezado: compañía, nº ticket `pos_reference`, camarero `user_id`, mesa si restaurante; líneas con qty/precio/variantes `attribute_value_ids`/notas `customer_note`; totales; método de pago; QR opcional con `order.uuid`) → `rpc('/lba_print/jobs', …)`. Si falla o no está configurado → `super.printReceipt(...)` (comportamiento nativo intacto).
2. **Comandas** — `patch(PosStore.prototype, { printChanges(order, orderChange, reprint, printers) })` (`pos_store.js` L2255): para cada `printer` con `printer.config.lba_printer_id`, convierte el `orderChange` ya calculado por el core (`new`/`cancelled`/`noteUpdate` — no se re-implementa nada) en payload con mesa, camarero, `pos_reference`, deltas con cantidades/variantes/notas → `rpc('/lba_print/jobs', …)`; impresoras sin mapeo LBA siguen el camino nativo. El patch respeta `updateLastOrderChange()` y `uiState.lastPrints` (antiduplicados nativos).
3. **Controlador** — `@http.route('/lba_print/jobs', type='jsonrpc', auth='user', csrf=False)` (patrón del core; `type='json'` está deprecado en 19): crea `lba.print.job` con `uuid` + `idempotency_key = order.uuid + hash(delta) + printer_id` y dispara un intento inmediato con `requests.post(..., timeout=2.5)`; si LBA no responde, el trabajo queda `pending` en la cola de Odoo (el TPV nunca se bloquea > 3 s).
4. **Cron** — `ir.cron` "LBA: reintentar trabajos" (cada minuto): procesa pendientes con backoff (5 s→300 s, máx. 5) y "LBA: actualizar estados" (cada 5 min) consulta `GET /jobs/{external_job_id}` para refrescar `sent/failed`.
5. **Errores de comunicación** — se muestran en el TPV con un toast no bloqueante (OWL `makeToast`/popup ligero) y quedan en la cola visible en el backend (vista `lba.print.job` con filtro por estado).

## 4. Menús y pantallas (backend Odoo)

- Menú raíz **LBA Print**: Servidor · Impresoras · Departamentos · Cola de trabajos.
- Formulario del servidor con botones **Probar conexión / Sincronizar impresoras** y estado (`state` + `last_message`).
- Departamentos: name + impresoras + categorías POS (multi), formulario tipo kanban/list.
- Cola: tree con `state`, `attempts`, `last_error`, acciones "Reintentar ahora" y "Cancelar".
- Ajustes del TPV (`pos.config`): en la pestaña de impresión del TPV, campos `lba_active`, `lba_receipt_printer_id`; formulario de `pos.printer` con `lba_printer_id`.

## 5. Anti-duplicados (capas)

1. TPV: `nb_print`/`canPrintReceipt` (nativo) y `uiState.lastPrints` (reimpresiones).
2. Odoo: `uuid` único de `lba.print.job` + `idempotency_key` compuesta.
3. LBA Server: `idempotency_key` única en SQLite (respuesta 409 con el job existente).

## 6. Pruebas del addon

- Unit tests (se ejecutan con el runner de Odoo): `tests/test_lba_server.py` (mock de `requests`), `tests/test_lba_job.py` (estados/reintentos), `tests/test_departments.py` (5 departamentos por defecto).
  ```bash
  odoo-bin -c … -d test_lba -i lba_print_connector \
      --test-tags /lba_print_connector --stop-after-init
  ```
- **Guía de validación en tu instancia local** (`tests/GUIDA_VALIDACION.md`): 12 pasos desde instalar el módulo hasta imprimir comanda de cancelación, incluida la comprobación de que el TPV no se congela si apagas LBA.

## 7. Qué NO hace (honestidad técnica)

- No sustituye pantallas de cocina (`pos_preparation_display`).
- No imprime en USB/Bluetooth desde el navegador del TPV (fuera de alcance; LBA es servidor de impresoras de red).
- No garantiza "impreso físicamente": los estados se propagan tal como LBA los reporta (`sent`).
- El reintento inmediato usa `requests` con `timeout` — está en `requirements.txt` de Odoo 19 (verificado), así que no añade dependencias Python al host Odoo.
