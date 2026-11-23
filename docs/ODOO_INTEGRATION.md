# Integración de LBA Print Connector con Odoo 19 Community

> Estado de esta rama: trabajo de corrección y QA en `fix/odoo19-addon-qa-layouts`. El código y las pruebas estáticas no equivalen a una instalación real de Odoo. Ver `ODOO_VALIDACION.md` para la matriz de evidencia vigente.

El addon (`odoo_addons/lba_print_connector`) depende de `point_of_sale` y `pos_restaurant`. Extiende modelos/vistas y parchea `PosStore` con OWL; no modifica archivos del core. La referencia de APIs Odoo 19 revisadas está en [`ODOO19_REFERENCE.md`](ODOO19_REFERENCE.md).

## 1. Instalación de desarrollo

La instalación limpia y la actualización se pretenden validar en GitHub Actions mediante [`.github/workflows/ci-odoo-addon.yml`](../.github/workflows/ci-odoo-addon.yml), usando Odoo 19.0 y PostgreSQL 16. El workflow está añadido en esta rama, pero no debe considerarse verde hasta que exista una ejecución completada con logs.

Para probar manualmente, usar únicamente una instancia de desarrollo/QA separada y una base de datos descartable autorizada. No instalar esta rama en la base de producción de Lo D’ Leo. El despliegue de una versión estable deberá seguir un plan de respaldo y migración revisado por el administrador.

## 2. Componentes del addon

| Modelo | Responsabilidad |
|---|---|
| `lba.print.server` | Conexión autenticada con LBA, comprobación de salud y sincronización de impresoras. |
| `lba.print.printer` | Réplica de impresoras LBA y perfil de ancho/columnas; los datos físicos desconocidos no se presuponen. |
| `lba.print.department` | Enrutamiento Odoo por departamentos y categorías POS, con una o más impresoras LBA y opción de fallback explícito. |
| `lba.print.template` / `.block` | Editor de bloques ordenados, alcance por impresora/departamento/general, vista previa de 58/80 mm y serialización segura. |
| `lba.print.job` | Cola durable de salida local, idempotencia, intentos, errores y consulta/retry remoto. |

Las reglas ACL y de compañía están declaradas en `security/`. Su comportamiento en una base real aún requiere ejecutar el workflow y comprobarlo en Odoo.

## 3. Flujo del TPV y estados

1. El TPV crea un registro `lba.print.job` local mediante `/lba_print/jobs`. La ruta valida impresora, compañía, departamento, tipo, payload y clave; una clave ya existente solo se acepta si coincide con impresora, pedido, departamento, tipo y payload. Una colisión con contenido distinto devuelve error.
2. Esta llamada no hace HTTP al servidor LBA. El TPV recibe el estado local `pending` y no espera por una impresora desconectada.
3. Un cron reclama trabajos con bloqueo `FOR UPDATE SKIP LOCKED` y envía el trabajo al servidor LBA. `queued` indica que LBA aceptó/encoló el trabajo; los errores y reintentos quedan registrados localmente.
4. La consulta periódica sincroniza el estado del trabajo remoto. `sent` significa que LBA informó transmisión de bytes al socket TCP, no que el papel haya salido ni que se haya confirmado físicamente.

| Estado Odoo | Semántica |
|---|---|
| `pending` | Guardado local y esperando despacho/reintento. |
| `queued` | LBA aceptó el trabajo; no equivale a impresión física. |
| `sent` | Bytes transmitidos según el servidor LBA; sin confirmación de papel. |
| `failed` / `cancelled` | Fallo agotado o cancelación registrada. |

La ejecución real del cron, el bloqueo bajo varios workers y el despacho ante fallos todavía deben validarse en Odoo/PostgreSQL. No se afirma entrega física.

## 4. Enrutamiento POS

- La configuración de `lba.print.department` es la única fuente de enrutamiento LBA. Las categorías POS asignadas a departamentos determinan qué productos entran en cada comanda; las reglas de categorías superpuestas en jerarquía se rechazan para evitar ambigüedad.
- Los productos sin categoría asignada a una ruta no deben entrar en el fallback. El fallback es explícito y filtra categorías ya cubiertas por departamentos asignados.
- Las impresoras de comanda Odoo que no se enrutan a LBA conservan la ruta nativa mediante `super`. Los recibos solo usan LBA cuando el TPV tiene LBA activado y una impresora de recibos configurada.
- No se envían tickets de delta vacíos.

Los detalles dependen de la estructura de datos POS de Odoo 19 descrita en `ODOO19_REFERENCE.md`; la ejecución OWL/navegador aún no está verificada.

## 5. Idempotencia y reimpresiones

Cada operación POS incluye una clave idempotente de hasta 200 caracteres, compatible con el patrón y longitud del servidor LBA. Repetir el mismo evento con el mismo documento converge en el mismo trabajo; reutilizar una clave para un payload distinto se rechaza. Los retries automáticos conservan la clave, mientras que una reimpresión intencional crea otra. Odoo y LBA conservan sus propios registros.

Los tests de Node cubren los builders y el serializador de plantillas; no sustituyen pruebas concurrentes en Odoo, navegador ni servidor conectado.

## 6. Diseñador de tickets

Las plantillas se componen de bloques ordenados (texto, campos dinámicos, reglas, tablas, condicionales, QR/código de barras, imagen, avance y corte). Campos, tablas y condiciones usan listas blancas; no se evalúan expresiones, JavaScript, Python, Jinja ni HTML arbitrario. El ancho se toma del perfil configurado (58/80 mm), sin deducir capacidades de una impresora desconocida.

El serializador de plantilla genera el documento usado por el flujo POS; la vista previa y la prueba de impresión usan el serializador del modelo. La equivalencia visual exacta entre ambos y la impresión en navegador/hardware sigue pendiente de una prueba de extremo a extremo. Una plantilla que no genere ningún bloque no debe imprimir un ticket vacío.

## 7. Verificación disponible y pendiente

Comandos previstos desde la raíz del repositorio:

```bash
node odoo_addons/lba_print_connector/tests/test_lba_templates.mjs
python3 -m compileall -q odoo_addons/lba_print_connector
# El workflow de GitHub instala Odoo 19 y ejecuta los TransactionCase.
```

El estado de cada comando y la ejecución real de `pytest`, GitHub Actions, instalación, navegador/E2E y hardware se registra en [`ODOO_VALIDACION.md`](ODOO_VALIDACION.md). No atribuir al addon validación de instalación hasta que haya evidencia de Odoo en ejecución.

## 8. Límites explícitos

- No sustituye `pos_preparation_display` ni confirma físicamente la salida del papel.
- No se han verificado el protocolo, el ancho, el modelo ni las funciones físicas de la impresora Volcora. Se conoce por reporte del usuario que es térmica y Wi-Fi para cocina; no se enviarán comandos ni se escaneará la LAN para identificarla sin autorización e identificación adecuada.
- USB/Bluetooth y periféricos fuera del servidor LBA de red quedan fuera del alcance actual.
