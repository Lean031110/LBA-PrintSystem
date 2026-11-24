# Diseñador visual de tickets LBA

## Alcance del diseño

El addon define `lba.print.template` y `lba.print.template.block`, con bloques ordenados, plantillas para recibo/comanda y ámbitos general, departamento o impresora. Una plantilla puede seleccionar perfil de ancho automático o simular papel térmico de 58/80 mm. En modo automático se usa el perfil conocido de la impresora; no se infiere el ancho de modelos desconocidos.

Tipos de bloque disponibles en el modelo:

- Texto fijo y campos dinámicos de lista blanca.
- Separador simple/doble y espacio/avance.
- Corte con líneas previas.
- QR y códigos de barras.
- Imagen configurada como base64.
- Condicionales con un solo nivel de sub-bloques.
- Tabla de nuevas/canceladas/modificadas/todas las líneas y pagos.

El modelo impone un máximo de 200 bloques, valida campos requeridos y solo evalúa nombres de campo, tablas y condiciones de listas blancas. No admite código del usuario, expresiones, HTML dinámico o plantillas Python/Jinja.

## Serialización y vista previa

`lba.print.template.to_document(data)` serializa bloques a un documento estructurado `{"type":"ticket","blocks":[...]}`. El wizard construye la vista previa térmica HTML y la impresión de prueba desde esa misma serialización Python y los mismos datos de muestra. El frontend POS usa `lba_templates.js`, un espejo JavaScript del contrato que construye el documento con datos reales del pedido y lo envía al controlador. No se genera ESC/POS dentro de Odoo.

La intención es que preview, prueba de impresora y POS compartan estructura, bloques y listas blancas. La equivalencia visual entre los dos serializadores y el resultado real de navegador/impresora todavía no está demostrada; requiere tests Odoo y un E2E con simulador. QR, código de barras y corte en preview son representaciones indicativas, no renderizados físicos exactos.

## Seguridad y límites

- El servidor valida nuevamente el documento estructurado mediante Pydantic antes de encolarlo.
- Las claves idempotentes usan solo ASCII `[A-Za-z0-9_:\-.]`, hasta 200 caracteres. El POS conserva la misma clave en retries y crea otra para reimpresión intencional.
- Las imágenes se limitan a 300 KiB decodificados en el servidor; el addon también valida imagen base64 antes de encolar.
- El ancho/papel y protocolo de la Volcora no se conocen ni se presuponen; no probar impresión física hasta identificar el modelo y las capacidades.

## Verificación

El test `tests/test_lba_templates.mjs` valida el serializador JS, las listas blancas, datos de muestra POS y claves. No prueba widgets/views Odoo ni OWL en navegador. La matriz completa de evidencia está en [`ODOO_VALIDACION.md`](ODOO_VALIDACION.md).
