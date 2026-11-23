# Validación de LBA Print Connector en Odoo 19

## Alcance y entorno seguro

Esta rama (`fix/odoo19-addon-qa-layouts`) está en QA. No instalarla ni correr migraciones sobre la base real de Lo D’ Leo. La instalación manual debe hacerse en una base aislada de desarrollo, con permisos y respaldo apropiados. Ninguna impresora física debe recibir comandos mientras su modelo, protocolo y capacidades no estén identificados.

## Estado de evidencia al 23 de noviembre de 2026

| Criterio | Estado | Evidencia / siguiente paso |
|---|---|---|
| Serializador JS, lista blanca y builders de claves | **Verificado localmente** | `node --test odoo_addons/lba_print_connector/tests/*.mjs`: 2 archivos de test pasaron, cubriendo templates y routing/failover. No prueba OWL. |
| Sintaxis Python del addon | **Verificado localmente** | `compileall` y parseo AST de Python pasaron; no carga modelos en Odoo. |
| Sintaxis de vistas XML | **Verificado localmente** | Parseo XML de todos los archivos del addon pasó; no sustituye carga de vistas en Odoo. |
| Sintaxis YAML de workflows | **Verificado localmente** | PyYAML parseó `.github/workflows/*.yml` sin errores; esto no valida la semántica de GitHub Actions ni reemplaza ejecutar el workflow editado. |
| Recursos de datos del manifest | **Verificado en CI** | Los 12 paths declarados existen y el paso de validación del manifest pasó. Los tres XML excluidos por el patrón antiguo de `.gitignore` ya están versionados. |
| Pruebas del servidor LBA (`pytest`) | **Verificado localmente y en CI** | Suite local: **60 passed, 46 warnings**. [Run CI 45285525809](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45285525809) es `success` sobre SHA `49f7249be25e518844de6d7fb5ea427ef08ef7dc`. |
| Suite de despliegue | **Verificado localmente y en CI** | `python3 -m unittest discover -s deploy/tests -v`: 22 passed; CI servidor pasó el mismo paso. Incluye mocks Proxmox y rutas temporales, no Proxmox ni LXC/systemd real. |
| Whitespace/conflictos del diff | **Verificado localmente** | `git diff --check` pasó después de las modificaciones actuales de README, CHANGELOG y documentos de QA. |
| Instalación limpia Odoo 19 / TransactionCase | **Verificado en CI** | [Run 45285525821](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45285525821), SHA `49f7249be25e518844de6d7fb5ea427ef08ef7dc`: resumen `0 failed, 0 error(s) of 28 tests`; se verificaron los fixtures Odoo 19 `group_ids` y el despacho selectivo. |
| Actualización del addon en base separada | **Verificado en CI** | El mismo run instaló una versión base en `lba_odoo19_upgrade` y ejecutó `-u lba_print_connector` más TransactionCase: resumen `0 failed, 0 error(s) of 28 tests`. No equivale a upgrade sobre datos de producción. |
| Paquetes QA Odoo/servidor | **Verificados para QA** | Runs `45285525809` y `45285525821` generaron archivos byte-a-byte idénticos para el SHA anterior; `SHA256SUMS` pasó en ambos. ZIP SHA-256 `99b9ee38541ac2ac1911c3e7100328c5ee173eb7256b84fc6c346000006a5147`; TAR SHA-256 `2d2159ab37fb0dcbdaa7bd6ca92dd5c30364558e407596a55b346237723ce1cd`. No es release estable ni instalación en LXC. |
| Navegador OWL y flujo TPV | **No verificado** | El CI no abre el navegador. Probar recibo, comanda, deltas, reimpresión, enrutamiento, fallback y rutas nativas en POS Odoo de desarrollo. |
| E2E Odoo ↔ servidor LBA | **No verificado** | El CI del servidor usa su propio simulador; no conecta el addon instalado a una instancia LBA. Probar desconexión, reintento, concurrencia y estados en ambiente aislado. |
| Varios workers Odoo / doble reclamo | **No verificado** | `FOR UPDATE SKIP LOCKED` está presente; aún falta prueba concurrente que lance varios workers sobre la misma cola. |
| Hardware Volcora / impresoras físicas | **No verificado** | No probar hasta conocer modelo, interfaz y protocolo; no escanear LAN indiscriminadamente. |

Los logs Odoo fueron descargados de `45285525821`. En ambos logs, instalación y
actualización, hay 28 entradas `Starting Test` y el resumen `odoo.tests.result`
informa 0 fallos/errores de 28 tests. La línea `odoo.tests.stats` informa 36
tests; esa diferencia de contadores se conserva como observación del log, sin
convertirla en una afirmación de cobertura adicional. También aparecen errores
SQL de unicidad esperados en tests con savepoints; no son fallos del run.

Las pruebas del servidor validan el servicio LBA y su simulador, no el flujo conectado desde el addon Odoo. La evidencia CI de instalación/upgrade tampoco valida el comportamiento OWL del navegador ni papel físico.

Como evidencia histórica separada, los runs 45237021879 (Odoo) y 45237021802 (servidor) ejecutaron en el SHA `d3c99b323c78af9b1bedcfa4f635391e44a3d0fe`; los runs 45239085651 y 45239085620 ejecutaron en `7ae0857d6ae9cf50f4d1c6470fe54171527e34ed`. Ninguno corresponde a los commits QA de código `47218c3`, `f899670` y `5e4d8dd` descritos en esta matriz.

## Comandos de QA local

Desde la raíz del repositorio:

```bash
node --test odoo_addons/lba_print_connector/tests/*.mjs
python3 -m unittest discover -s deploy/tests -v
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

## Resultados históricos de CI (SHA anteriores)

El workflow `.github/workflows/ci-odoo-addon.yml` está configurado con PostgreSQL 16 y código oficial Odoo 19.0 para: (1) instalación limpia con tests del addon y (2) instalación de una versión base en otra base seguida por `-u` y tests. El run histórico **45237021879** pasó ambas fases, un test Node y la validación de recursos del manifest; no valida los cambios locales ni la cobertura Node ampliada en esta revisión.

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
