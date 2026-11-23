# Validación de LBA Print Connector en Odoo 19

## Alcance y entorno seguro

Esta rama (`fix/odoo19-addon-qa-layouts`) está en QA. No instalarla ni correr migraciones sobre la base real de Lo D’ Leo. La instalación manual debe hacerse en una base aislada de desarrollo, con permisos y respaldo apropiados. Ninguna impresora física debe recibir comandos mientras su modelo, protocolo y capacidades no estén identificados.

## Estado de evidencia al 23 de noviembre de 2026

| Criterio | Estado | Evidencia / siguiente paso |
|---|---|---|
| Serializador JS, lista blanca y builders de claves | **Verificado localmente** | `node odoo_addons/lba_print_connector/tests/test_lba_templates.mjs` pasó; incluye igualdad/diferencia de IDs deterministas de deltas, clave de reimpresión y plantilla vacía. No prueba OWL. |
| Sintaxis Python del addon | **Verificado localmente** | `python3 -m compileall -q odoo_addons/lba_print_connector` pasó; no carga modelos en Odoo. |
| Sintaxis de vistas XML | **Verificado localmente** | Parser XML pasó para 11 XML; no comprueba herencia/resolución de vistas de Odoo. |
| Sintaxis YAML de workflows | **Verificado localmente** | PyYAML pudo parsear `ci-odoo-addon.yml` y `ci-server.yml`; no valida semántica/ejecución de Actions. |
| Pruebas del servidor LBA (`pytest`) | **Verificado localmente** | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q`: **44 passed**, 27 warnings (1 deprecación Starlette/httpx y 26 de adaptador datetime SQLite/Python 3.12). |
| Whitespace/conflictos del diff | **Verificado localmente** | `git diff --check` pasó en esa corrida; repetir tras los cambios finales antes de commit. |
| Instalación limpia Odoo 19 / TransactionCase | **Pendiente** | Workflow `.github/workflows/ci-odoo-addon.yml`; aún hace falta un run GitHub completado y revisar logs. |
| Actualización del addon en base separada | **Pendiente** | Segundo job de base de datos del workflow; todavía sin resultado de ejecución. |
| Navegador OWL y flujo TPV | **No verificado** | Probar recibo, comanda, deltas, reimpresión, enrutamiento, fallback y rutas nativas en POS Odoo real/de prueba. |
| E2E Odoo ↔ servidor LBA | **No verificado** | Base Odoo aislada y simulador LBA; comprobar desconexión, reintento, concurrencia y consistencia de estados. |
| Hardware Volcora / impresoras físicas | **No verificado** | No probar hasta conocer modelo, interfaz y protocolo; no escanear LAN indiscriminadamente. |

Las pruebas de servidor validan el servicio LBA, no el addon Odoo. El estado de GitHub no se considera verde por tener el workflow definido.

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

## CI de Odoo previsto

`.github/workflows/ci-odoo-addon.yml` define dos fases aisladas con PostgreSQL 16 y código oficial Odoo 19.0: (1) instalación limpia con tests del addon y (2) instalación de una base de actualización seguida por `-u` y tests. El workflow también ejecuta el test Node y valida que existan los ficheros declarados por el manifest.

**Pendiente:** observar un run real en GitHub, revisar ambos logs y corregir los errores que aparezcan. La definición del workflow no demuestra que las dependencias, el manifest, vistas, ACL, constraints ni TransactionCase funcionen.

## Checklist manual aislado (cuando CI instale correctamente)

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
