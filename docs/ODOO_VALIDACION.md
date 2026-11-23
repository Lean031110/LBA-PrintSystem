# Validación de LBA Print Connector en Odoo 19

## Alcance y entorno seguro

Esta rama (`fix/odoo19-addon-qa-layouts`) está en QA. No instalarla ni correr migraciones sobre la base real de Lo D’ Leo. La instalación manual debe hacerse en una base aislada de desarrollo, con permisos y respaldo apropiados. Ninguna impresora física debe recibir comandos mientras su modelo, protocolo y capacidades no estén identificados.

## Estado de evidencia al 23 de noviembre de 2026

| Criterio | Estado | Evidencia / siguiente paso |
|---|---|---|
| Serializador JS, lista blanca y builders de claves | **Verificado localmente** | `node odoo_addons/lba_print_connector/tests/test_lba_templates.mjs` pasó; incluye igualdad/diferencia de IDs deterministas de deltas, clave de reimpresión y plantilla vacía. No prueba OWL. |
| Sintaxis Python del addon | **Verificado localmente** | `python3 -m compileall -q odoo_addons/lba_print_connector` pasó; no carga modelos en Odoo. |
| Sintaxis de vistas XML | **Verificado localmente** | Se parsearon los 11 XML del addon; la vista `lba.print.job.search` también pasó el RNG `search_view` oficial de Odoo 19. |
| Sintaxis YAML de workflows | **Verificado localmente** | PyYAML parseó `ci-odoo-addon.yml` y `ci-server.yml`; ambos workflows ejecutaron correctamente en GitHub. |
| Recursos de datos del manifest | **Verificado en CI** | Los 12 paths declarados existen y el paso de validación del manifest pasó. Los tres XML excluidos por el patrón antiguo de `.gitignore` ya están versionados. |
| Pruebas del servidor LBA (`pytest`) | **Verificado en CI** | [Run 45237021802](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45237021802): **44 tests passed** y smoke end-to-end con simulador, API, worker y panel. Una ejecución local anterior tuvo 27 warnings de deprecación (Starlette/httpx y adaptador datetime de SQLite/Python 3.12). |
| Whitespace/conflictos del diff | **Verificado localmente** | `git diff --check` pasó tras las correcciones y tras actualizar estos documentos, antes de publicar. |
| Instalación limpia Odoo 19 / TransactionCase | **Verificado en CI** | [Run 45237021879](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45237021879), SHA `d3c99b323c78af9b1bedcfa4f635391e44a3d0fe`: instalación en base aislada, Odoo reporta 22 tests y 0 fallidos/errores (resumen de carga: 16 tests). |
| Actualización del addon en base separada | **Verificado en CI** | El mismo run instaló la versión base en una segunda BD y luego ejecutó `-u lba_print_connector`; el log de upgrade reporta 22 tests y 0 fallidos/errores. |
| Navegador OWL y flujo TPV | **No verificado** | El CI no abre el navegador. Probar recibo, comanda, deltas, reimpresión, enrutamiento, fallback y rutas nativas en POS Odoo de desarrollo. |
| E2E Odoo ↔ servidor LBA | **No verificado** | El CI del servidor usa su propio simulador; no conecta el addon instalado a una instancia LBA. Probar desconexión, reintento, concurrencia y estados en ambiente aislado. |
| Varios workers Odoo / doble reclamo | **No verificado** | `FOR UPDATE SKIP LOCKED` está presente y el cron pasa TransactionCase, pero aún falta prueba concurrente que lance varios workers sobre la misma cola. |
| Hardware Volcora / impresoras físicas | **No verificado** | No probar hasta conocer modelo, interfaz y protocolo; no escanear LAN indiscriminadamente. |

Las pruebas del servidor validan el servicio LBA y su simulador, no el flujo conectado desde el addon Odoo. La evidencia CI de instalación/upgrade tampoco valida el comportamiento OWL del navegador ni papel físico.

## Comandos de QA local

Desde la raíz del repositorio:

```bash
node odoo_addons/lba_print_connector/tests/test_lba_templates.mjs
python3 -m compileall -q odoo_addons/lba_print_connector
python3 - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
files = sorted(Path("odoo_addons/lba_print_connector").rglob("*.xml"))
for path in files:
    ET.parse(path)
print(f"XML parse OK: {len(files)} archivos")
PY
```

Para la suite del servidor, crear/activar un entorno virtual dentro de `server/` e instalar únicamente sus dependencias de desarrollo:

```bash
cd server
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest -q
```

El virtualenv está excluido por `.gitignore` y no reemplaza herramientas globales.

## Resultados del CI de Odoo

`.github/workflows/ci-odoo-addon.yml` ejecuta con PostgreSQL 16 y código oficial Odoo 19.0: (1) instalación limpia con tests del addon y (2) instalación de una versión base en otra base seguida por `-u` y tests. El run final **45237021879** pasó ambas fases, el test Node y la validación de recursos del manifest.

Los logs de instalación y actualización fueron revisados. Incluyen dos sentencias de unicidad deliberadamente rechazadas por los tests (código de departamento y clave idempotente), dentro de savepoints; los resúmenes Odoo reportan 0 fallos y 0 errores. GitHub también muestra un aviso de mantenimiento porque `actions/checkout@v4`, `setup-python@v5` y `upload-artifact@v4` apuntan a Node.js 20, que el runner fuerza a Node.js 24; no hizo fallar los workflows.

El CI del servidor **45237021802** pasó 44 tests y el smoke con simulador. Este smoke no incluye el addon Odoo. No se ejecutaron pruebas en la base real de Lo D’ Leo.

## Checklist manual aislado (pendiente aunque CI esté verde)

1. Crear una base de desarrollo vacía, separada de producción, instalar `point_of_sale` y `pos_restaurant`, y probar instalación del addon.
2. Confirmar menús, vistas, ACL y reglas multicompañía con un usuario administrador y un usuario POS apropiado.
3. Configurar servidor LBA de prueba y una impresora simulada; no usar la Volcora no identificada.
4. Abrir una sesión POS de prueba; confirmar que se cargan impresoras, departamentos, categorías, plantillas y bloques.
5. Validar recibo y pre-cuenta y comparar ticket renderizado con la vista previa 58/80 mm.
6. Validar comanda con categorías asignadas a varios departamentos, cambios de cantidad, cancelación y nota modificada.
7. Verificar que artículos sin categoría asignada no se imprimen y que el fallback configurado no roba artículos asignados a otro departamento.
8. Confirmar que impresoras nativas continúan funcionando y que no se emite trabajo de delta vacío.
9. Repetir el mismo evento y simular timeout; confirmar que se conserva clave y trabajo. Ejecutar reimpresión intencional y confirmar clave distinta.
10. Apagar el servicio LBA de prueba durante una comanda: el POS no debe esperar a la impresora; el trabajo debe permanecer local y recuperarse tras reactivar el servicio.
11. Ejecutar más de un worker sobre trabajos pendientes y comprobar que ningún trabajo es reclamado por dos procesos.
12. Verificar semántica: `pending` local, `queued` aceptado por LBA, `sent` enviado al socket, sin alegar papel impreso.
13. Revisar logs, cola y payloads; no conservar datos de prueba no autorizados ni ejecutar estas pruebas en producción.

Registrar fecha, versiones, entorno, resultado, logs sanitizados y desviaciones. No incluir tokens ni contraseñas en el repositorio o en los logs adjuntos.
