# Auditoría final — evidencia QA y límites

> **La actualización de evidencia más reciente está en el addendum final de CI.** Las secciones A–F conservan los hallazgos y causas del baseline `7ae0857d6ae9cf50f4d1c6470fe54171527e34ed`; las líneas originales “Resultado actual” describen ese baseline. La reevaluación previa y los hallazgos G1–G11 son contexto de cambios anteriores. El addendum final prevalece para el estado actual de CI/artefactos; nada de ello constituye aprobación de producción ni gate de release.

## Contexto y alcance

- Rama revisada: `fix/odoo19-addon-qa-layouts`.
- HEAD baseline: `7ae0857d6ae9cf50f4d1c6470fe54171527e34ed`.
- `origin/main` existe en `2b6266ecadd2d5eefd9444f5a8da14fd62272b5a`. Este dato es contexto del repositorio, no una recomendación ni autorización para integrar cambios.
- `feature/lba-print-foundation` está en `1a92097af53e7014fdedb050469eef92bc615183` y **no debe tocarse**.
- No había un PR asociado a la rama revisada.
- El baseline se inspeccionó inicialmente de forma estática; los cambios se separaron en commits QA de servidor (`47218c3`), despliegue (`f899670`) y addon Odoo (`5e4d8dd`) sobre la misma rama. A este corte aún no se habían publicado esos commits ni ejecutado su CI; los tests locales y los dos runs remotos descritos abajo pertenecen a evidencia separada. No se desplegó producción, no se accedió a datos de Lo D’ Leo, no se escaneó LAN ni se interactuó con impresoras físicas.

## Cómo leer los resultados

Los hallazgos y sus causas describen problemas detectados en la inspección estática original. «Prueba necesaria» es el gate originalmente propuesto. La columna “Resultado actual” de cada hallazgo se conserva como contexto del baseline; la reevaluación final indica qué se corrigió, probó o sigue pendiente. La gravedad conserva las clasificaciones de origen.

### Separación de evidencia de pruebas

- **Automatizadas locales ejecutadas:** servidor 60 passed (46 warnings); despliegue 22 passed (mocks/temporales); Node 2 archivos passed. También pasaron Bash `-n` (8 scripts), compileall/AST Python (55 archivos), parseo XML (11 archivos), parseo YAML (2 workflows) y `git diff --check`. TransactionCase, navegador, E2E y LXC reales no se ejecutaron.
- **CI remoto:** runs 45239085620 (servidor) y 45239085651 (Odoo) terminaron success, ambos en SHA base `7ae0857d6ae9cf50f4d1c6470fe54171527e34ed`; no validan cambios locales posteriores.
- **Simuladas/físicas:** tests con simulator/mocks no modelan emisión térmica. No hubo pruebas físicas; no se comprobó corte, legibilidad del QR/barcode, modelo, papel ni confirmación física. No se accedió a producción ni LAN.

## Inventario de áreas cubiertas

1. Instalación, actualización, copias de seguridad, restauración, desinstalación y unidades systemd.
2. Aprovisionamiento de CT en Proxmox y walkthrough de demostración.
3. Servidor/API, autenticación, panel, persistencia SQLite, auditoría, cola, worker, reintentos y recuperación.
4. Contrato POS e integración Odoo: controlador, permisos, cola/cron, routing de impresoras, reintentos e idempotencia.
5. Rendering ESC/POS, simulador, preview, plantillas, diseñador y límites de las pruebas observadas.
6. CI, dependencias, compatibilidad, empaquetado, checksums, releases y atribución de evidencia por SHA.
7. Exactitud de documentación de seguridad, contrato API, compatibilidad, instalación y estado de CI.

## Hallazgos

### A. Instalación, operaciones y despliegue

#### A1. El instalador no instala las tres unidades systemd que luego intenta habilitar
- **Problema:** La primera copia instala solo `lba-print-api.service`; el fallback que copiaría `*.service` solo corre si falla esa copia. Después se intenta habilitar/iniciar también `lba-print-worker.service`. El simulador tampoco queda instalado aunque se sugiera habilitarlo.
- **Gravedad:** Alta.
- **Archivo/líneas:** `deploy/scripts/install.sh:74-77, 91`.
- **Causa:** La alternativa de copia está condicionada al fallo del `cp` de la unidad API en vez de copiar explícitamente cada unidad.
- **Impacto:** En una instalación limpia puede faltar el worker y fallar `systemctl enable --now`; el simulador anunciado tampoco queda disponible.
- **Solución propuesta:** Copiar explícitamente las unidades necesarias desde una ruta basada en `REPO_DIR` o `INSTALL_DIR`, antes de `daemon-reload`, y comprobar la presencia de cada unidad antes de habilitarla.
- **Prueba necesaria:** En Debian/Ubuntu limpio o LXC desechable, verificar la instalación de las unidades y el resultado de habilitar/iniciar los servicios.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A2. La inicialización SQLite precede al cambio de propietario de `/var/lib/lba`
- **Problema:** El instalador crea `VAR_DIR` como root y ejecuta `init_db` como `lba` antes de hacer `chown` del directorio.
- **Gravedad:** Alta.
- **Archivo/líneas:** `deploy/scripts/install.sh:30, 56-71`; relacionado: `server/app/core/config.py:18-20`, `server/app/database/db.py:25-35`.
- **Causa:** El directorio recién creado puede conservar propietario root mientras la aplicación intenta crear SQLite/WAL con usuario `lba`.
- **Impacto:** En una ruta nueva no escribible por `lba`, la inicialización puede fallar antes de llegar al `chown`. No necesariamente afecta una ruta preexistente que ya tenga permisos compatibles.
- **Solución propuesta:** Asignar y validar propietario/permisos antes de `init_db`, también en actualizaciones y reinstalaciones.
- **Prueba necesaria:** Instalación desechable con `/var/lib/lba` inexistente; confirmar que `lba` crea DB/WAL y que el flujo continúa.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A3. El instalador usa `sudo` sin declararlo ni comprobarlo
- **Problema:** Los cambios de usuario se hacen con `sudo -u`, aunque los paquetes base listados no incluyen `sudo` y el uso indicado es como root en el contenedor.
- **Gravedad:** Alta.
- **Archivo/líneas:** `deploy/scripts/install.sh:23-27, 35-38, 56-62`.
- **Causa:** Se presupone la disponibilidad de `sudo` sin instalarlo, comprobarlo ni ofrecer alternativa.
- **Impacto:** En una imagen mínima Debian/Ubuntu sin `sudo`, el instalador puede detenerse durante la creación del entorno virtual o la inicialización.
- **Solución propuesta:** Usar una herramienta disponible y comprobada como `runuser`/`su`, o declarar e instalar `sudo` antes de usarlo.
- **Prueba necesaria:** Ejecutar el flujo en imagen mínima soportada sin `sudo` preinstalado y verificar el mecanismo seleccionado.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A4. El destino inicial del backup puede no ser escribible por `lba`
- **Problema:** `backup.sh` crea el directorio de salida y después invoca SQLite como `lba` para escribir dentro. En el caso documentado de primera ejecución como root, con directorio ausente y sin permisos/propiedad previos compatibles, el nuevo directorio queda normalmente propiedad de root.
- **Gravedad:** Alta.
- **Archivo/líneas:** `deploy/scripts/backup.sh:5-13`; referencia de ejecución: `deploy/scripts/update.sh:8-14`.
- **Causa:** No se prepara el directorio con permisos compatibles con el usuario que escribe.
- **Impacto:** En ese escenario SQLite no puede crear la copia, por lo que el backup y el backup previo de actualización no son fiables. No se afirma que falle en todo entorno.
- **Solución propuesta:** Preparar el directorio y los artefactos con permisos seguros para el proceso que escribe, y comprobar/propagar el fallo.
- **Prueba necesaria:** Como root y con `/var/backups/lba` inexistente, verificar código de salida, creación/legibilidad de DB válida y modos previstos.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A5. La actualización ignora fallos del backup previo
- **Problema:** `update.sh` usa `backup.sh ... || true` y luego sincroniza código con `--delete`.
- **Gravedad:** Alta.
- **Archivo/líneas:** `deploy/scripts/update.sh:8-14`.
- **Causa:** El estado de salida del backup se suprime incondicionalmente.
- **Impacto:** La actualización puede sobrescribir código y continuar sin una copia recuperable, incluso ante fallos de permisos o SQLite.
- **Solución propuesta:** Abortar por defecto si falla el backup y reportar el motivo. Cualquier excepción operativa debe requerir opción explícita y advertencia registrada.
- **Prueba necesaria:** Simular fallo del backup y comprobar que la actualización no modifica el árbol instalado ni inicia migraciones por defecto.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A6. Los archivos de backup con configuración/secretos no reciben modo restrictivo explícito
- **Problema:** Se empaqueta `/etc/lba-print`, potencialmente con secretos en `lba-print.env`, sin `umask` ni modo explícitos para el tar generado.
- **Gravedad:** Media.
- **Archivo/líneas:** `deploy/scripts/backup.sh:10-13, 19`.
- **Causa:** El modo del nuevo archivo depende de la `umask` y de los permisos del directorio de salida.
- **Impacto:** Con una umask habitual `022`, un archivo podría ser legible por otros usuarios locales si el directorio también lo permite. El modo efectivo no fue inspeccionado ni probado.
- **Solución propuesta:** Aplicar `umask 077` y validar/aplicar permisos restrictivos al directorio y a cada artefacto, incluyendo copias existentes.
- **Prueba necesaria:** Comprobar modos efectivos bajo umasks admitidas y que un usuario no autorizado no puede leer backup/secretos.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A7. Restore comprueba siempre el puerto 8000
- **Problema:** La verificación de salud posterior usa `127.0.0.1:8000` aunque `LBA_PORT` es configurable y se entrega a la unidad API.
- **Gravedad:** Media.
- **Archivo/líneas:** `deploy/scripts/restore.sh:17` (también documentado en la auditoría como `restore.sh:15-18`); `server/app/core/config.py:23-25`.
- **Causa:** Restore no lee el `EnvironmentFile` ni la configuración efectiva del servicio.
- **Impacto:** Con un puerto distinto de 8000, el servicio puede iniciar y la comprobación reportar fallo de forma incorrecta.
- **Solución propuesta:** Leer y validar `LBA_PORT` con el mismo default que la aplicación/unidad y usarlo en health check.
- **Prueba necesaria:** Restaurar en entorno de prueba con puerto no predeterminado y verificar que se consulta el puerto configurado.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A8. Un error a mitad de restore puede dejar los servicios detenidos
- **Problema:** Se detienen API y worker antes de completar validaciones; con `set -e`, fallos de instalación o extracción detienen el script y no hay recuperación/rollback de servicios.
- **Gravedad:** Media.
- **Archivo/líneas:** `deploy/scripts/restore.sh:4, 9-15`.
- **Causa:** La parada antecede a la validación completa y no existe trap o manejo controlado de salida.
- **Impacto:** Una ruta de DB inválida, permisos insuficientes o configuración inválida puede dejar el servicio fuera de línea hasta intervención manual.
- **Solución propuesta:** Validar insumos antes de parar, preparar restauración atómica y añadir recuperación segura que no arranque una DB parcialmente reemplazada y comunique el estado.
- **Prueba necesaria:** Inyectar errores en cada etapa en entorno aislado y comprobar servicios e integridad de DB.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A9. La desinstalación predeterminada elimina configuración
- **Problema:** La rama por defecto elimina `/etc/lba-print` además de `/opt/lba`, aunque conserva `/var/lib/lba`; `--purge-data` se presenta como opción de purga.
- **Gravedad:** Media.
- **Archivo/líneas:** `deploy/scripts/uninstall.sh:12-18`.
- **Causa:** La eliminación de configuración no está condicionada a `--purge-data` ni a confirmación separada.
- **Impacto:** Se conservan datos/DB, pero se pierden ajustes locales y secretos; la reinstalación no restaura por sí sola esa configuración.
- **Solución propuesta:** Definir y documentar política; conservar configuración por defecto y eliminarla solo con opción explícita, o advertir y ofrecer exportación antes de borrarla.
- **Prueba necesaria:** Probar uninstall con y sin `--purge-data`, comprobando por separado DB y configuración.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A10. Proxmox oculta errores de descarga de plantilla
- **Problema:** `pveam download ... || true` suprime cualquier error y el script sigue a `pct create` con el nombre esperado.
- **Gravedad:** Media.
- **Archivo/líneas:** `deploy/proxmox/create_lba_ct.sh:14-19`.
- **Causa:** No se distingue plantilla ya presente de descarga fallida y no se valida disponibilidad/integridad local.
- **Impacto:** Fallos de red, almacenamiento o plantilla inválida se manifiestan como error posterior menos claro.
- **Solución propuesta:** Comprobar si ya existe; si no, conservar/reportar el error de descarga y verificar plantilla antes de crear CT.
- **Prueba necesaria:** Probar plantilla presente, descarga fallida y almacenamiento no disponible; solo el primer caso debe continuar sin descarga.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A11. La creación de CT no es idempotente ante reejecución
- **Problema:** Se usa CTID fijo por defecto (215) y se llama siempre a `pct create` sin comprobar existencia ni reconciliar estado.
- **Gravedad:** Media.
- **Archivo/líneas:** `deploy/proxmox/create_lba_ct.sh:7-8, 18-27`.
- **Causa:** La creación es una operación única, no una operación segura para reintentar.
- **Impacto:** Reejecutar tras éxito o ejecución parcial falla por CTID ocupado y no diferencia contenedor conforme de conflicto.
- **Solución propuesta:** Diagnosticar conflicto de forma no destructiva o validar propiedades del CT existente y tratar como éxito solo si coincide con lo solicitado.
- **Prueba necesaria:** En Proxmox de prueba, ejecutar dos veces y con CTID ocupado por configuración distinta; verificar resultados deterministas y no destructivos.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### A12. El walkthrough permite operaciones mutativas contra una URL remota
- **Problema:** `BASE` puede apuntar a cualquier URL; el walkthrough envía POST de registro, discovery, creación de trabajos y autenticación con credenciales demo predeterminadas.
- **Gravedad:** Media.
- **Archivo/líneas:** `deploy/scripts/demo_walkthrough.sh:15-19, 36-50, 64-76`.
- **Causa:** No se exige loopback ni confirmación explícita para destino remoto.
- **Impacto:** Una invocación accidental puede modificar un sistema remoto, transmitir credenciales demo o ejecutar discovery. No se contactó ningún destino durante las auditorías.
- **Solución propuesta:** Restringir modo demo a loopback o requerir habilitación remota explícita con aviso; evitar credenciales estáticas por defecto en destino remoto.
- **Prueba necesaria:** Confirmar que loopback funciona y que URL remota se rechaza sin opción explícita.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

### B. Servidor, datos, seguridad y cola

#### B1. El worker puede recuperar trabajos `processing` que otro worker aún procesa
- **Problema:** Cada arranque llama a `recover_orphan_processing`, que devuelve indiscriminadamente todos los trabajos `processing` a `pending`, sin distinguir claim activo.
- **Gravedad:** Alta.
- **Archivo/líneas:** `server/app/worker/__main__.py:97-104`; `server/app/models/models.py:192-200`.
- **Causa:** El claim no registra lease, propietario/worker ni heartbeat; la recuperación se decide solo por estado.
- **Impacto:** Un segundo worker puede volver a reclamar y enviar el mismo trabajo mientras el primero sigue activo, causando duplicados y estados inconsistentes. También existe replay si el proceso cae después de enviar bytes y antes del commit: TCP raw no aporta acuse físico ni exactly-once.
- **Solución propuesta:** Registrar propietario y lease/heartbeat, recuperar solo claims vencidos y coordinar el arranque. Documentar semántica at-least-once y crear conciliación/manual para resultados ambiguos si no hay destino con deduplicación fiable.
- **Prueba necesaria:** Prueba con dos workers donde uno conserve claim activo; prueba de caída entre `sendall` y commit con simulador, revisando reclamos, bytes recibidos y política de recuperación.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### B2. La clave idempotente no se valida contra impresora ni contenido
- **Problema:** La clave es globalmente única y la búsqueda de duplicados solo considera `idempotency_key`; reutilizarla con otra impresora o documento devuelve el job anterior.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/models/models.py:46-52`; `server/app/services/queue_service.py:19-35`; `server/app/api/routes.py:222-241`.
- **Causa:** No se compara `printer_id` ni huella canónica del payload, y la unicidad no tiene ámbito de cliente/impresora.
- **Impacto:** La comanda puede asociarse a impresora equivocada o perderse como nueva solicitud; el API responde 409 con job potencialmente distinto.
- **Solución propuesta:** Definir ámbito explícito, guardar huella estable y rechazar reutilización incompatible en vez de tratarla como duplicado equivalente.
- **Prueba necesaria:** Misma clave con misma petición, distinta impresora y distinto payload; comprobar deduplicación legítima y conflictos/no pérdida.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### B3. El borrado de impresora desde el panel falla si conserva historial de jobs
- **Problema:** La ruta bloquea trabajos `pending/processing` pero elimina `Printer` sin borrar/desvincular jobs terminales ni eventos asociados; la FK no define `ON DELETE` y SQLite tiene `foreign_keys` activado.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/dashboard/routes_panel.py:200-218`; `server/app/models/models.py:46-52, 70-78`; `server/app/database/db.py:39-46`.
- **Causa:** La ruta del panel no aplica la limpieza/transacción del endpoint API.
- **Impacto:** Con historial `sent`, `failed` o `cancelled`, el commit puede violar FK y dar 500, sin completar el borrado.
- **Solución propuesta:** Unificar en servicio transaccional y definir política de archivo/desvinculación o borrado con confirmación y auditoría; manejar violación con respuesta controlada.
- **Prueba necesaria:** Crear job terminal, borrar por panel y verificar respuesta y política de conservación del historial.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### B4. Guardar la edición de dispositivo en el panel invoca `get` sobre un booleano
- **Problema:** La expresión `bool(p.settings or {}).get("logo", False)` intenta llamar `get` en un booleano.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/dashboard/routes_panel.py:271-286`, en particular `278-282`.
- **Causa:** Se convierte el diccionario a booleano antes de leer la clave `logo`.
- **Impacto:** La edición válida de dispositivo alcanza esa expresión y falla antes del commit.
- **Solución propuesta:** Consultar `(p.settings or {}).get("logo", False)`, validar tipo y conservar el ajuste al reemplazar `settings`.
- **Prueba necesaria:** POST de edición con ajustes vacíos/no vacíos; validar respuesta, commit y persistencia de todos los campos, incluido `logo`.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### B5. La cookie de sesión no fuerza atributo `Secure`
- **Problema:** `lba_session` tiene `httponly` y `samesite=lax`, pero no `secure=True`; la app no configura TLS y escucha por defecto en `0.0.0.0:8000`.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/dashboard/routes_panel.py:98-102`; `server/app/main.py:21-37`; `server/app/core/config.py:23-25`.
- **Causa:** No se fuerza transporte HTTPS ni se condiciona la cookie a terminación TLS segura.
- **Impacto:** Si el servicio o proxy publica HTTP, el navegador puede enviar la cookie sin cifrar. No se verificó TLS/proxy del despliegue real; no se afirma que HTTPS esté habilitado o ausente externamente.
- **Solución propuesta:** Exigir HTTPS en perímetro, emitir cookie `Secure` cuando corresponda y definir explícitamente modo TLS/proxy; no permitir acceso HTTP autenticado.
- **Prueba necesaria:** Revisar configuración real de proxy y comprobar headers de cookie por HTTPS y comportamiento de acceso HTTP.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### B6. Los fallos de token inválido no quedan persistidos en el registro de auditoría
- **Problema:** `check_token` añade `AuditLog` y lanza 401 sin commit; al cerrar la sesión se revierte la transacción.
- **Gravedad:** Baja.
- **Archivo/líneas:** `server/app/api/deps.py:23-33`; `server/app/database/db.py:59-65`.
- **Causa:** Falta commit explícito o mecanismo duradero independiente antes de devolver 401; a diferencia de `check_ip`, esa ruta no confirma el evento.
- **Impacto:** Los intentos de token inválido no aparecen en la auditoría persistente, reduciendo trazabilidad de abuso.
- **Solución propuesta:** Persistir el evento de forma segura antes del 401, idealmente en transacción independiente o middleware que no lo pierda al revertir la petición.
- **Prueba necesaria:** Enviar token inválido y consultar `AuditLog` tras cerrar petición; confirmar que registra ruta/IP y no token/secreto.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### B7. `/health` público revela conteos internos y la documentación no lo refleja
- **Problema:** El endpoint sin autenticación había devuelto conteos de impresoras y trabajos por estado, contrariamente a la política en `docs/SECURITY.md`.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/api/routes.py:68-76`; `docs/SECURITY.md:8, 34`; `server/tests/test_auth.py:7-14`.
- **Causa:** La ruta serializaba métricas de cola/inventario y no delimitaba el esquema público.
- **Impacto:** El endpoint revelaba actividad e inventario operativo a cualquier cliente con acceso de red.
- **Solución aplicada:** `/health` devuelve solo `status`, `app`, `version` y `uptime_s`, consulta `jobs` para readiness y traduce error SQL a 503 genérico; `/stats` sigue autenticado. La política de `docs/SECURITY.md` ya corresponde.
- **Prueba:** `test_health_publico` fija lista permitida de claves y ausencia de conteos; `test_health_no_disponible_si_sqlite_no_esta_lista` verifica 503 genérico.
- **Resultado actual:** Corregido; suite servidor **60/60 pass**.

#### B8. `discovery_ranges` guardado no restringe el escaneo
- **Problema:** El panel conserva/muestra `discovery_ranges`, pero `discovery.scan` no consulta ese ajuste; `_network_ok` aplica límites de redes privadas/loopback de `PRINTER_ALLOWED_NETS` y máximo de hosts, no la lista guardada.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/dashboard/routes_panel.py:297-320, 505-519`; `server/app/services/discovery.py:23-48, 68-76`; `server/app/core/config.py:27-38`.
- **Causa:** El rango guardado se trata como configuración/UI y no como allowlist efectiva.
- **Impacto:** Un operador puede creer que limita el escaneo, aunque una llamada válida pueda especificar otros rangos privados. No se ejecutó discovery ni se escaneó LAN.
- **Solución propuesta:** Definir si es sugerencia o control; si es control, exigir que CIDR solicitado esté contenido en rango guardado y documentar política.
- **Prueba necesaria:** Tests aislados para rango permitido, privado fuera de lista, link-local/público y límite de hosts; sin escaneo LAN.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

### C. Odoo, POS y autorización

#### C1. El RPC POS encola trabajos sin exigir grupo ni contexto POS autorizado
- **Problema:** Ruta `auth='user'` eleva consultas/creación con `sudo()` y verifica compañía, pero no exige grupo POS, sesión/configuración POS activa, `lba_active` ni impresora asignada a esa configuración; `department_id` es opcional.
- **Gravedad:** Media.
- **Archivo/líneas:** `odoo_addons/lba_print_connector/controllers/main.py:28-53, 68-75`.
- **Causa:** La autorización se reduce a pertenencia de compañía antes de `sudo`, sin vincular pedido, sesión y configuración POS accesibles.
- **Impacto:** Un usuario interno autenticado de la compañía podría solicitar trabajos arbitrarios a una impresora activa y consumir la cola.
- **Solución propuesta:** Validar grupo/contexto POS, compañía del pedido, sesión/configuración, impresora asignada y departamento donde aplique; usar `sudo` solo después de controles.
- **Prueba necesaria:** En Odoo aislado, comparar usuario no POS, usuario POS sin sesión/configuración activa y usuario POS autorizado; solo el último debería encolar.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### C2. «Procesar ahora» puede despachar globalmente la cola desde método expuesto a POS
- **Problema:** `action_process_now()` delega al cron; SQL directo reclama hasta 50 pendientes globales sin filtrar por registro ni compañía. El botón se muestra a trabajos pendientes; ACL de POS concede lectura/creación, no escritura, y no se observó control explícito de grupo. Puede hacerse POST remoto antes de que falle el `write` ORM.
- **Gravedad:** Alta.
- **Archivo/líneas:** `odoo_addons/lba_print_connector/models/lba_job.py:192-193, 208-235`; `views/lba_job_views.xml:36-38`; `security/ir.model.access.csv:8`.
- **Causa:** Se reutiliza el cron como acción pública; SQL omite ACL/reglas y el efecto HTTP precede a la actualización local protegida.
- **Impacto:** Un usuario POS podría disparar trabajos ajenos, incluso de otras compañías; un fallo posterior puede dejar aceptación remota sin estado local confirmado y favorecer reenvíos.
- **Solución propuesta:** Restringir botón/método a gestores y separar cron privado de acción de usuario. Si se conserva acción manual, procesar solo `self` con controles de compañía/permisos y evitar HTTP antes de asegurar estado local.
- **Prueba necesaria:** En instancia aislada, invocar como POS y comprobar que no procesa otros registros ni envía externamente; verificar multi-compañía y usuario sin `write`.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### C3. El routing POS envía a todas las impresoras activas, no solo a una primaria
- **Problema:** El patch itera todos los `printerRefs` activos del departamento y crea trabajo para cada uno; el modelo/documentación describe primaria más respaldo.
- **Gravedad:** Media.
- **Archivo/líneas:** `odoo_addons/lba_print_connector/static/src/app/pos_store_patch.js:313-326, 385-407`; referencia `models/lba_department.py:28-33, 127-135`.
- **Causa:** No selecciona solo primera impresora ni implementa failover.
- **Impacto:** Con varias impresoras activas puede imprimirse repetidamente la misma comanda/delta.
- **Solución propuesta:** Acordar semántica: una primaria con failover controlado, o fan-out explícito documentado y configurable. Evitar duplicar destinos ya aceptados.
- **Prueba necesaria:** Routing con dos impresoras activas: una aceptación normal y failover solo ante fallo de primaria.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### C4. Una colisión 409 con job remoto fallido pierde el ID de recuperación
- **Problema:** Al recibir 409, se extrae `detail.job`, pero si su estado es `failed` se devuelve `False` y se descarta ID; el endpoint retry requiere `external_job_id` conocido.
- **Gravedad:** Media.
- **Archivo/líneas:** `odoo_addons/lba_print_connector/models/lba_server.py:171-190`; contrato local `server/app/api/routes.py:235-240`, `283-293`; `docs/API_CONTRACT.md:27, 115`.
- **Causa:** La rama de colisión trata trabajo fallido como error genérico en vez de conservar su identidad y retry.
- **Impacto:** Si el POST original fue aceptado pero la respuesta se perdió y el trabajo remoto falló, nuevos POST reciben el mismo conflicto; retry normal local no puede recuperar el job y se requieren intentos/intervención fuera del flujo previsto.
- **Solución propuesta:** Persistir ID/estado remoto en 409 incluso si está fallido y permitir retry sobre ese ID, o consultar por clave idempotente antes de reintentar.
- **Prueba necesaria:** Simular POST aceptado con respuesta perdida, estado remoto `failed` y segundo POST 409; comprobar ID conservado y uso de `/jobs/{id}/retry`.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### C5. Acciones de servidor visibles no concuerdan con ACL de solo lectura
- **Problema:** `base.group_user` tiene lectura, pero menú y acciones «Probar conexión»/«Sincronizar impresoras» no están restringidos; las acciones escriben servidor o crean/actualizan impresoras.
- **Gravedad:** Baja.
- **Archivo/líneas:** `odoo_addons/lba_print_connector/security/ir.model.access.csv:2-3`; `views/lba_menus.xml:3-11`; `views/lba_server_views.xml:28-33`; `models/lba_server.py:80-98, 101-145`.
- **Causa:** UI/métodos se exponen a usuarios con ACL insuficiente, sin restricción de grupo o delegación de mínimos privilegios.
- **Impacto:** Usuarios internos pueden ver acciones que terminan en `AccessError`; «Probar conexión» puede hacer GET remoto antes de fallar el write.
- **Solución propuesta:** Restringir menú, botones y métodos a administradores/gestores apropiados o implementar acción autorizada con permisos mínimos.
- **Prueba necesaria:** Validar visibilidad/ejecución con usuario base, POS manager y administrador en Odoo aislado.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

### D. Renderizado, preview y semántica de impresión

#### D1. El serializador JS reduce los bloques `spacer` a una línea
- **Problema:** Para `spacer`, JavaScript evalúa `feed_lines` antes que `spacer_lines`; ambos tienen default 1, por lo que un `spacer_lines > 1` puede quedar reducido a 1. Python usa `spacer_lines` para ese tipo.
- **Gravedad:** Media.
- **Archivo/líneas:** `odoo_addons/lba_print_connector/static/src/app/lba_templates.js:167-169`; `odoo_addons/lba_print_connector/models/lba_template.py:539-542`.
- **Causa:** Se combinan spacer y feed en una expresión con prioridad de campos distinta de ramas Python separadas.
- **Impacto:** POS puede omitir espacio configurado y diferir de preview/prueba.
- **Solución propuesta:** Separar `spacer` y `feed` en JS y leer sus respectivos campos; cubrir paridad Python/JS.
- **Prueba necesaria:** Serializadores Python y JS con defaults y valores >1 para spacer/feed; comparar documentos y luego bytes en simulador, sin inferir salida física.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### D2. El parser de preview no consume el payload variable de QR ESC/POS
- **Problema:** La rama `GS ( k` avanza una cantidad fija en vez de interpretar `pL/pH` y el contenido QR de longitud variable.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/services/preview.py:96-103`; `server/tests/test_rendering.py:46-60, 74-82`.
- **Causa:** Decodificador aproximado con salto fijo para `GS ( k`.
- **Impacto:** La reconstrucción puede interpretar bytes del payload como texto/comandos o perder correspondencia con bytes posteriores; la prueba de preview no valida consumo correcto del QR.
- **Solución propuesta:** Parsear subcomandos y longitudes ESC/POS o mantener QR opaco, con fixtures de longitudes variables.
- **Prueba necesaria:** Comparar previews de varios QR con bytes capturados por simulador y verificar que no haya texto residual ni desalineación posterior.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### D3. La preview térmica Odoo es esquemática, no representa bytes ESC/POS
- **Problema:** El wizard genera HTML directamente desde documento estructurado. QR es recuadro con texto y barcode un gradiente fijo ajeno al valor/simbología; no ejecuta renderer ESC/POS.
- **Gravedad:** Informativa.
- **Archivo/líneas:** `odoo_addons/lba_print_connector/models/lba_preview_wizard.py:71-98, 100-149`; `models/lba_template.py:290-307`.
- **Causa:** Es una ilustración HTML y no una representación de bytes ni un emulador físico.
- **Impacto:** Usuarios pueden interpretar dimensiones, códigos, wrapping o detalles como fieles. Compartir `to_document` no demuestra igualdad visual/física.
- **Solución propuesta:** Rotularla explícitamente como esquemática; para mayor fidelidad, generar bytes con renderer común y representarlos con emulador apropiado, sin equiparar eso a validación física.
- **Prueba necesaria:** Integración Odoo→servidor/simulador que compare documento, bytes y render; pruebas visuales 58/80 mm y QR/barcode. No afirmar fidelidad actual.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### D4. El estado `sent` no acredita impresión física ni exactly-once
- **Problema:** Worker marca `sent` tras `sendall`; no recibe confirmación física fiable. Caída después del envío y antes del commit puede reencolar y repetir.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/worker/__main__.py:45-57`; `server/app/services/queue_service.py:118-127`; contrato `docs/API_CONTRACT.md:123`; Odoo `models/lba_job.py:60-62`.
- **Causa:** TCP raw confirma el envío de bytes al socket, no recepción/impresión física; la recuperación no puede distinguir envío previo de fallo previo.
- **Impacto:** Entrega al menos una vez en esa ventana y posible duplicado de recibo/comanda. No existe evidencia para afirmar impresión física o exactamente una vez.
- **Solución propuesta:** Mantener semántica documentada explícitamente; añadir conciliación/estado ambiguo o protocolo/destino con deduplicación fiable antes de reenvío automático.
- **Prueba necesaria:** Prueba controlada de caída entre `sendall` y commit con simulador para observar estados y número de documentos recibidos; hardware requeriría validación aparte.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

### E. CI, dependencias, releases y trazabilidad

#### E1. Dependencias sin versiones exactas ni hashes
- **Problema:** Requirements usan límites inferiores abiertos; no hay lockfile/hash y workflows/instalador resuelven versiones disponibles al ejecutarse. Herramientas como `pip`, `wheel` y `rtlcss` tampoco quedan fijadas en los pasos indicados.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/requirements.txt:1-10`; `server/requirements-dev.txt:2-4`; `.github/workflows/ci-server.yml:18-21`; `.github/workflows/ci-odoo-addon.yml:47-61`; `deploy/scripts/install.sh:35-38`.
- **Causa:** Dependencias Python declaradas con mínimos y ausencia de lock/checksums; herramientas globales dinámicas.
- **Impacto:** Dos ejecuciones del mismo commit pueden instalar conjuntos diferentes; reconstrucción de entorno menos reproducible.
- **Solución propuesta:** Lockfile con hashes usado en CI e instalación; fijar herramientas relevantes y versión de `rtlcss`, documentando base del sistema.
- **Prueba necesaria:** Resolver desde cero en entornos limpios, confirmar mismo lock en CI/instalador y rechazo de versión/hash no aprobado.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### E2. CI de servidor no instala `requirements-dev.txt` que usa como clave de caché
- **Problema:** El workflow usa `server/requirements-dev.txt` como `cache-dependency-path`, pero instala requirements de servidor y después `pytest/httpx` directamente.
- **Gravedad:** Baja.
- **Archivo/líneas:** `.github/workflows/ci-server.yml:16-23`; `server/requirements-dev.txt:1-5`.
- **Causa:** El manifiesto de caché no es el manifiesto efectivamente instalado para tests.
- **Impacto:** Dependencias de test pueden divergir y cambios en el archivo dev no describen fielmente el entorno ejecutado.
- **Solución propuesta:** Instalar `requirements-dev.txt` y fijar/hashear dependencias, o alinear clave de caché con manifiestos reales.
- **Prueba necesaria:** Comparar entorno limpio instalado por CI con `requirements-dev.txt` y verificar invalidación de caché pertinente.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### E3. CI Odoo clona una rama mutable de Odoo 19
- **Problema:** El workflow clona con profundidad 1 `odoo/odoo` rama `19.0`, sin fijar SHA.
- **Gravedad:** Media.
- **Archivo/líneas:** `.github/workflows/ci-odoo-addon.yml:55-56`.
- **Causa:** Se referencia una rama upstream que avanza en vez de commit inmutable.
- **Impacto:** No se puede reconstruir con certeza el core probado; cambios upstream alteran resultados aunque SHA LBA no cambie.
- **Solución propuesta:** Fijar SHA de Odoo aprobado, registrar versión y actualizarla mediante cambio deliberado revisado.
- **Prueba necesaria:** Ejecutar workflow con revisión fijada y comprobar que logs identifican SHA Odoo y commit LBA.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### E4. No hay matriz que contraste versiones/plataformas declaradas
- **Problema:** Cada job usa una sola configuración Python 3.12; no hay `strategy.matrix`. La compatibilidad declarada para servidor contempla Python 3.10+.
- **Gravedad:** Baja.
- **Archivo/líneas:** `.github/workflows/ci-server.yml:8-17`; `.github/workflows/ci-odoo-addon.yml:12-15, 40-43`; `docs/COMPATIBILITY.md:10-13`.
- **Causa:** Workflows tienen una sola versión/runner, sin enumerar combinaciones.
- **Impacto:** No hay evidencia automatizada sobre versiones inferiores declaradas ni otras plataformas objetivo.
- **Solución propuesta:** Si se mantiene soporte 3.10+, añadir matriz de versiones; documentar con precisión combinaciones excluidas y objetivo del addon.
- **Prueba necesaria:** Ejecutar matriz en runners limpios y registrar resultados por combinación.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### E5. No se observa construcción de paquete/ZIP con integridad verificable
- **Problema:** Workflows publican logs de prueba Odoo como artifact; el workflow servidor no declara artifact. No se encontró flujo de build de ZIP addon o paquete servidor, checksum, descarga/verificación; changelog afirma ZIP descargable sin mecanismo observado que lo produzca.
- **Gravedad:** Media.
- **Archivo/líneas:** `.github/workflows/ci-odoo-addon.yml:125-135`; `.github/workflows/ci-server.yml:18-29`; `CHANGELOG.md:109-112`.
- **Causa:** Workflows revisados ejecutan pruebas/cargan logs, no empaquetan ni validan integridad.
- **Impacto:** En este repositorio no se identifica una ruta automatizada para obtener y verificar artefactos instalables reproducidos desde commit. Esto no permite concluir que no haya procesos externos.
- **Solución propuesta:** Añadir empaquetado explícito y normalizado, SHA-256, verificación del paquete y asociación a SHA/CI; revisar afirmación de changelog.
- **Prueba necesaria:** Construir dos veces desde el mismo SHA en entornos limpios, comparar contenido/hash, verificar checksum descargado e instalación desde estructura empaquetada.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### E6. No se observa flujo de release estable por tag
- **Problema:** Workflows revisados disparan por ramas y PR; no se observó trigger de tags/release ni pasos para publicar paquetes.
- **Gravedad:** Media.
- **Archivo/líneas:** `.github/workflows/ci-odoo-addon.yml:3-7`; `.github/workflows/ci-server.yml:2-5`; `CHANGELOG.md:20, 109-112`.
- **Causa:** Archivos inspeccionados implementan CI, no promoción/release trazable.
- **Impacto:** El repositorio no documenta/automatiza una promoción de commit probado a versión estable con artefactos y checksums. No se comprobó configuración remota ni procesos externos.
- **Solución propuesta:** Diseñar release por tag autorizado que exija gates, genere paquetes/checksums y registre tag, SHA y herramientas; distinguir versiones publicadas de documentación local.
- **Prueba necesaria:** Probar proceso con tag de prueba autorizado y verificar gate, SHA y checksums publicados.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### E7. La evidencia documental de CI es de otro SHA, no del baseline auditado
- **Problema:** README y documentos atribuyen runs previos a `d3c99b323c78af9b1bedcfa4f635391e44a3d0fe`, mientras el HEAD auditado es `7ae0857d6ae9cf50f4d1c6470fe54171527e34ed`.
- **Gravedad:** Media.
- **Archivo/líneas:** `README.md:62-67`; `docs/ODOO_VALIDACION.md:14-19, 56-62`; `CHANGELOG.md:8-13`.
- **Causa:** La evidencia almacenada no identifica una ejecución asociada al HEAD actual.
- **Impacto:** Los resultados históricos no prueban que el baseline haya pasado checks; no se consultó GitHub ni se ejecutaron workflows en esta auditoría.
- **Solución propuesta:** Vincular cada resultado/artefacto a SHA exacto y marcar ejecuciones anteriores como históricas; actualizar estado solo tras verificar run del SHA correspondiente.
- **Prueba necesaria:** Consultar ejecución completada del SHA baseline y comparar SHA de evento, logs, checks y artifacts.
- **Resultado actual:** Pendiente; evidencia documental histórica observada para SHA `d3c99b...`; no se ejecutó ni verificó externamente para HEAD baseline.

### F. Documentación y contrato de comportamiento

#### F1. La documentación describe backup combinado distinto de los artefactos observados
- **Problema:** La guía describe un tar combinado con DB, mientras el script produce un `.db` y un archivo de configuración separado.
- **Gravedad:** Alta (agrupada con el fallo operativo de backup A4-A5; discrepancia documental adicional).
- **Archivo/líneas:** `deploy/scripts/backup.sh:10-13, 19`; `deploy/scripts/update.sh:8-10`; `docs/PROXMOX_INSTALLATION.md:58-65`; `CHANGELOG.md`.
- **Causa:** La guía no refleja la salida efectiva del script inspeccionado.
- **Impacto:** El operador puede esperar un artefacto distinto o creer que existe un backup combinado que el script no produce.
- **Solución propuesta:** Tras definir el formato y corregir permisos/propagación de errores, alinear guía y changelog con nombres, contenido y retención reales.
- **Prueba necesaria:** Generar backup en CT descartable, inspeccionar artefactos y contrastar guía/formato/permisos; no se ejecutó.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### F2. `density` se acepta/documenta pero renderer no la aplica
- **Problema:** El esquema permite `density` y la matriz la presenta como configurable, pero `render_document` no lee esa clave ni emite comando de densidad.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/schemas/schemas.py:140-146`; `server/app/services/rendering.py:55-72, 143-150`; `docs/COMPATIBILITY.md:36-48`.
- **Causa:** Campo expuesto en configuración sin implementación correspondiente en renderer.
- **Impacto:** Cambiar el ajuste no altera bytes y puede crear expectativa incorrecta de control físico.
- **Solución propuesta:** Marcarlo como no implementado hasta implementación/prueba; actualizar compatibilidad y roadmap.
- **Prueba necesaria:** Comparar bytes con density activado/desactivado; validación física solo con hardware identificado y autorizado.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### F3. El selector `profile` no elige perfil de capacidades por dispositivo
- **Problema:** El renderer fija `ESCPOS_PROFILE` a `default` y no consulta profile del dispositivo, aunque esquema/documentación sugieren selección de perfiles.
- **Gravedad:** Media.
- **Archivo/líneas:** `server/app/services/rendering.py:25-43`; `server/app/schemas/schemas.py:148-159, 165-176`; `docs/COMPATIBILITY.md:21-34`.
- **Causa:** `profile` queda como metadata sin mapeo efectivo a capacidades python-escpos.
- **Impacto:** El selector no aplica características específicas; no debe inferirse compatibilidad de modelo a partir de ese campo.
- **Solución propuesta:** Implementar perfiles admitidos con mapeo validado o corregir documentación para declarar uso de `default`.
- **Prueba necesaria:** Tests del perfil efectivo por configuración; compatibilidad física requiere identificar y probar hardware.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### F4. `API_CONTRACT.md` documenta códigos HTTP distintos de implementación
- **Problema:** El contrato asigna 403 a token inválido y 400 a payload inválido; el código devuelve 401 para token inválido, 403 para IP denegada y FastAPI/Pydantic 422 para payload inválido.
- **Gravedad:** Baja.
- **Archivo/líneas:** `docs/API_CONTRACT.md:27`; `server/app/api/deps.py:23-33`; `server/app/schemas/schemas.py:106-115`; `server/tests/test_auth.py:17-24`; `server/tests/test_jobs.py:45-65`.
- **Causa:** La tabla contractual no refleja el comportamiento observado en código y tests existentes.
- **Impacto:** Consumidores que sigan el contrato pueden tratar incorrectamente errores de auth y payload.
- **Solución propuesta:** Alinear tabla con 401 token, 403 IP, 422 validación y 400 errores explícitos; usar tests como contrato ejecutable después de ejecutarlos.
- **Prueba necesaria:** Ejecutar tests aislados y comparar respuestas/OpenAPI con la tabla revisada.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

#### F5. `ODOO_INTEGRATION.md` se contradice sobre estado CI
- **Problema:** Una sección dice no considerar verde el workflow hasta ejecución completada; más adelante consigna instalación limpia/upgrade como pasados en run 45237021879. Esta auditoría no consultó el run externamente.
- **Gravedad:** Baja.
- **Archivo/líneas:** `docs/ODOO_INTEGRATION.md:7-11, 71-77`; `README.md:60-72`; `CHANGELOG.md:6-14`.
- **Causa:** Texto inicial no se actualizó al documentar evidencia posterior.
- **Impacto:** Estado de CI ambiguo; además, los resultados documentados se atribuyen a un SHA distinto del baseline.
- **Solución propuesta:** Confirmar run en fuente autorizada antes de publicar estado y distinguir SHA/run históricos de estado vigente; revisar estados del roadmap.
- **Prueba necesaria:** Verificar run y SHA asociados en registro de CI y alinear documentos.
- **Resultado actual:** Pendiente; no ejecutado en esta auditoría.

## Áreas sin defectos encontrados en la inspección estática

Lo siguiente describe controles observados en código/configuración revisados; no equivale a comprobar su funcionamiento efectivo en ejecución:

- Las unidades systemd declaran usuario/grupo `lba` y directivas de endurecimiento (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ReadWritePaths=/var/lib/lba`, `ProtectHome`); API y simulador declaran `Restart=always`/`RestartSec`, y worker incluye `RestartSec=5`. No se verificó el estado de servicios ni la retención/acceso a journal.
- SQLite se configura con WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=15000` y timeout de conexión 15 s. Esto no demuestra permisos ni comportamiento en runtime.
- Se observó persistencia de jobs/eventos, backoff exponencial con máximo, límites de intentos, retención y recuperación de `processing`; el problema de recuperación concurrente/ambigua está descrito en B1. Worker no se ejecutó.
- Hay límites declarativos Pydantic por bloque, validación de IP, discovery restringido a redes privadas/loopback configuradas y límite de hosts, allowlist IP cliente, token API y rate limit en memoria. No se probaron en red; `discovery_ranges` del panel no equivale a allowlist efectiva (B8).
- Las rutas operativas API usan autenticación; `/health` y documentación/OpenAPI permanecen públicos por configuración. `/health` devuelve datos mínimos y consulta SQLite/schema antes de responder readiness; no serializa inventario ni actividad.
- Las plantillas HTML revisadas usan autoescape Jinja normal; no se encontró salida explícitamente marcada como segura en las vistas revisadas.
- La denegación por IP confirma su evento de auditoría, a diferencia de la ruta de token inválido descrita en B6.
- El patch de POS conserva `super.printChanges()` para impresoras nativas en esa ruta. Cuando LBA está activo y hay impresora de recibo LBA, `printReceipt` reemplaza la llamada `super`; no se comprobó el flujo en navegador.

## Límites de verificación y cobertura pendiente

1. La suite del servidor pasó **60 tests con 46 warnings**; la suite de despliegue pasó **22 tests** usando temporales, sudo y mocks; los dos módulos de test Node pasaron. Esto verifica código dentro del sandbox, no instalación ni operación en producción.
2. Los estáticos locales (`bash -n`, `compileall`/AST Python, parseo XML/YAML y `git diff --check`) ya pasaron; no acreditan la semántica de GitHub Actions ni reemplazan el run nuevo.
3. Los runs GitHub 45239085620 (server) y 45239085651 (Odoo) concluyeron success en SHA base `7ae0857d6ae9cf50f4d1c6470fe54171527e34ed`; no cubren modificaciones locales sin commit. El workflow modificado/pinneado todavía no se ejecutó en GitHub.
4. No se ejecutó instalación en Debian 12/LXC, `systemd-analyze verify` de servicios instalados, reinicio de CT, navegador OWL, TransactionCase de esta revisión, E2E Odoo→LBA ni multiworker concurrente real. Tampoco se validaron crashes ambiguos, stress, disco lleno ni funcionamiento offline bloqueando egress.
5. No se verificó HTTPS/TLS/SAN/renovación, cookie `Secure`, firewall efectivo, permisos del entorno de producción, instalación/actualización en rutas estándar o el comportamiento en otras versiones/plataformas.
6. El empaquetador se ejecutó/reprodujo contra el SHA base anterior a los cambios locales; aún no existen paquetes del commit actual ni comprobación de descarga/hashes de artefactos finales.
7. Los tests QR nuevos usan bytes ESC/POS sintéticos para validar `pL/pH`; no son bytes de un hardware físico ni demuestran legibilidad de un QR. El simulador es receptor TCP/reconstructor textual, no emulador físico.
8. No se probó impresora física, ni se contactó la base de producción de Lo D’ Leo. No se ejecutó discovery ni escaneo LAN; no se enviaron comandos a hardware. No se declara `sent` como papel impreso.

## Plan de priorización propuesto

Este plan ordena el trabajo técnico sugerido por riesgo y dependencias; **no es una autorización para mergear ni una indicación de estado listo**.

1. Ejecutar workflows en un commit de QA de esta rama; inspeccionar logs y descargar/validar artifacts por SHA/hashes.
2. Instalar/actualizar/backup/restore/reinstall/uninstall en LXC Debian 12 descartable con systemd real y comprobar persistencia tras reinicio; mantener producción intacta.
3. Ejecutar TransactionCase del nuevo addon en PostgreSQL/Odoo pinneado; completar browser/OWL y E2E Odoo→LBA→simuladores, incluidas rutas nativas y ACL.
4. Probar claims con múltiples workers/procesos, caída entre envío y commit, timeout/escritura parcial, reinicio y reconciliación sin afirmar exactly-once.
5. Resolver HTTPS interno, cookie `Secure`, firewall/offline y revisar dependencias lock/hash/matriz Python antes de release.
6. Corregir idempotencia/errores Proxmox; documentar `profile`/`density`; construir paquetes solo desde un SHA validado y comprobar descarga SHA-256.
7. No integrar en `main`, no publicar stable ni desplegar producción mientras sigan pendientes las gates obligatorias de aceptación del prompt.

## Reevaluación posterior a las correcciones (estado del worktree local)

La siguiente matriz prevalece sobre los “Resultado actual: Pendiente” escritos para el baseline en cada hallazgo. **Corregido** indica cambio local más prueba indicada; **Parcial** indica una mitigación/evidencia incompleta; **Pendiente** indica que no se implementó o no hay evidencia suficiente. Todos los cambios de código siguen sin commit a la fecha de esta captura, así que los runs remotos no los prueban.

| ID | Estado actual | Solución/evidencia y límite |
|---|---|---|
| A1 | Parcial | Instalador copia unidades explícitas y verifica disponibilidad; no existe test de instalación en LXC/systemd real. |
| A2 | Parcial | Se ordenó ownership/permisos antes de SQLite; ejecución con usuario `lba` en Debian limpio pendiente. |
| A3 | Parcial | `lib_common.sh` usa `runuser`/mecanismo verificado en el script; install real en imagen mínima pendiente. |
| A4 | Corregido | Backup root-only, checksum/permisos y rechazo de symlinks/hardlinks; tests de backup/restaurabilidad incluidos en suite local (22/22). |
| A5 | Corregido | Update aborta si backup falla antes de rsync; test de no modificación pasó. |
| A6 | Corregido | `umask 077`, directorio 0700, archivos 0600 y checksums probados en temporal; no prueba política de backup fuera del sandbox. |
| A7 | Corregido | Restore usa puerto del env restaurado; test con puerto 8765 comprobó URL de readiness. |
| A8 | Parcial | Rollback DB/config por fallo de health y de movimiento probado con mocks; proceso systemd real/LXC no probado. |
| A9 | Corregido | Desinstalación preserva config/datos por defecto y purga solo con flag; ambos recorridos probados. |
| A10 | Parcial | Proxmox no silencia fallo de descarga y no crea CT si falla; reutiliza archivo local existente sin verificar criptográficamente su identidad. Tests mock no consultan Proxmox. |
| A11 | Parcial | Detecta CTID ocupado y aborta sin operaciones template/create; test mock pasó. No reconcilia como éxito un CT existente idéntico, ni se ejecutó en Proxmox. |
| A12 | Corregido | Walkthrough rechaza URL remota por defecto y URL con userinfo; usa directorio 0700 para datos/cookie/logs y los elimina por defecto; regresiones estáticas/remotas incluidas en suite de despliegue. Permiso remoto explícito requiere `LBA_DEMO_ALLOW_REMOTE=1`. |
| B1 | Parcial | Lease y evento de claim ahora se escriben juntos; tests de worker pasaron. Sigue pendiente estrés real multiproceso y ventana `sendall`→commit. |
| B2 | Parcial | Dedupe compara impresora/payload canónico y reconcilia colisiones `IntegrityError`/`SQLITE_BUSY_SNAPSHOT`; regresión simulada pasó en 60/60. Stress concurrente multiproceso sigue pendiente. |
| B3 | Corregido | Impresoras con historial se archivan sin borrar jobs; reimpresión a destino archivado/inactivo ahora devuelve 409; regresiones API pasaron en 60/60. |
| B4 | Corregido | Corregida lectura booleana de settings y se ejecutó suite del servidor/panel. |
| B5 | Pendiente | Atributo `Secure`, TLS y configuración proxy no implementados/verificados; SECURITY ahora lo declara explícitamente. |
| B6 | Corregido | Evento por token inválido se persiste antes del 401; test de auth incluido en 60/60. |
| B7 | Corregido | `/health` omite conteos/inventario y comprueba que SQLite/schema responda; falla con 503 si DB no está lista; tests de health pasaron en 60/60. |
| B8 | Corregido | Rangos configurados restringen discovery; suite de discovery ejecutada sin escaneo LAN real. |
| C1 | Parcial | Controlador exige sesión POS/configuración/impresora; ORM y ACL deniegan creación directa tanto a usuarios POS como managers, y el controlador llama `sudo()` tras validar. ACL de departamentos deja routing solo editable por managers/admin. TransactionCase ampliado; parseo/compile local pasó, runtime Odoo aún pendiente. |
| C2 | Parcial | Acciones manuales limitadas a manager y a registro seleccionado; test Odoo añadido, runtime TransactionCase pendiente. |
| C3 | Parcial | Routing primaria y failover solo ante rechazo explícito; test Node de routing pasó. Falta navegador OWL y POS real. |
| C4 | Parcial | Solo se acepta 409 con `detail.job.id` string y `status` string de la lista conocida; 409 textual, sin estado o malformado es fallo. TransactionCase ampliado, aún no ejecutado en runtime Odoo. |
| C5 | Parcial | Menús/acciones de conexión y sync restringidos a `base.group_system`, HTTP protegido antes de operar; TransactionCase local pendiente. |
| D1 | Corregido | JS separa `spacer`/`feed`; Node templates/lista blanca pasó. |
| D2 | Corregido | Preview consume `pL/pH` y payload `GS ( k`, incluso >255 bytes; pruebas sintéticas variables/truncadas pasaron (12/12 rendering). Preview sigue siendo best-effort. |
| D3 | Pendiente | Vista previa Odoo sigue esquemática; no representa bytes ESC/POS ni ticket físico. |
| D4 | Parcial | Documentación mantiene `sent`=bytes al socket, no papel; caída ambigua y deduplicación exactly-once no están resueltas. |
| E1 | Pendiente | Aún no hay lockfile/hash íntegro de runtime/CI ni matrix limpia. |
| E2 | Parcial | Workflow de servidor instala `requirements-dev.txt`; el YAML/run actualizado aún requiere validación CI. |
| E3 | Parcial | Workflow fija Odoo SHA `62c2f793058de87ff453532f206a96a1e71845d2`; no existe run del workflow editado que certifique el pin. |
| E4 | Pendiente | No hay matrix que pruebe Python 3.10+ y plataformas declaradas. |
| E5 | Parcial | Builder determinista y artifact QA añadidos; reproducibilidad anterior fue solo sobre SHA base, no hay paquetes finales del código actual ni descarga/hash comprobado. |
| E6 | Pendiente | No se creó workflow/tag de release y no se publica release estable. |
| E7 | Parcial | GitHub confirmó runs 45239085620/45239085651 `success` en SHA base `7ae0857...`; trabajo actual local sin CI asociado. |
| F1 | Corregido | Guía ahora describe `.db`, `lba-config-*.tar.gz` y checksum separados; pruebas backup/restore pasaron en mocks/temp. |
| F2 | Pendiente funcional | Compatibilidad ahora declara `density` no implementada; no se simuló ni validó hardware. |
| F3 | Pendiente funcional | Compatibilidad ahora aclara que `profile` no selecciona capacidades; faltan mapeo y tests por perfil. |
| F4 | Corregido | API contract documenta 401 token, 403 IP y 422 Pydantic; suite server reejecutada 60/60. |
| F5 | Corregido documentalmente | Integración/QA atribuye CI a SHA base y separa cambios locales; run 45239085651 verificado externamente en el SHA indicado. |

### Hallazgos adicionales descubiertos durante la reevaluación

Esta sección complementa los 41 hallazgos A1–F5; no los reemplaza. Los resultados locales indican ejecución en sandbox y no implican gate de producción.

| ID / gravedad | Archivo y problema | Causa | Solución aplicada o pendiente | Prueba / resultado |
|---|---|---|---|---|
| G1 / P1 | `deploy/scripts/restore.sh`: restore de configuración podía cambiar permisos del directorio padre de staging y dejar archivos extraídos demasiado permisivos. | `install -d -m 0700` con stage predeterminado `/etc` podía aplicar chmod al directorio existente; solo el archivo env raíz se normalizaba. | El stage predeterminado es el padre de `ENV_DIR`; `mkdir -p` no cambia el modo preexistente y `mktemp` crea un hijo 0700. Tras instalar config, todos los directorios quedan 0750 y los archivos regulares 0640. | `test_restore_preserves_stage_root_mode_and_normalizes_all_config_permissions`; **pass** en suite deploy (22/22), usa directorio temporal que representa `/etc`; no tocó `/etc` del host. |
| G2 / P1 | `deploy/scripts/backup.sh` y `validate_config_archive.py`: el backup podía incluir enlaces que el restore después rechaza. | Backup copiaba `ENV_DIR` con `cp -a` sin validar tipos; archive validator prohíbe symlinks/hardlinks. | Después de copiar al staging privado, backup falla cerrado ante symlink o archivo regular hardlinkeado; no publica conjunto parcial. | `test_backup_rejects_symlink_and_hardlink_config` más backup válido; **pass** en suite deploy (22/22). |
| G3 / P1 | `odoo_addons/lba_print_connector/models/lba_job.py`, `security/ir.model.access.csv`, `views/lba_menus.xml`, `controllers/main.py`: POS/manager podía crear jobs por ORM o reconfigurar categorías/impresoras de departamentos fuera del endpoint autorizado. | El guard exceptuaba `group_pos_manager`, ACL permitía create a `group_pos_user` y write a departamentos para todo POS; menú general de departamentos no restringía manager. | El modelo bloquea `create` directo de cualquier POS no-sudo; ACL job quita create al POS, departamento queda read-only para POS users y editable por manager/admin, menú limitado a esos grupos. El controlador ejecuta `sudo().create` solo tras validar sesión, compañía, impresora y departamento. | TransactionCase `test_pos_user_y_manager_no_pueden_crear_job_directamente_por_orm_rpc` y `test_solo_manager_pos_puede_editar_rutas` añadidos. Compileall/AST y XML pasan localmente; TransactionCase no ejecutado sin Odoo/PostgreSQL. |
| G4 / P1 | `odoo_addons/lba_print_connector/models/lba_server.py`: un 409 remoto podía aceptarse con ID pero sin `status`, marcándolo como `queued`. | La validación usaba `pending` como estado por defecto cuando faltaba el campo `status`. | Solo se acepta `detail.job` con ID string no vacío y `status` string perteneciente a la lista conocida; respuesta textual, sin estado o malformada se convierte en fallo reintentable, no éxito. | TransactionCase `test_409_sin_job_identificable_no_se_acepta` y `test_409_con_id_sin_estado_no_se_acepta`; añadidos, runtime Odoo/PostgreSQL pendiente. |
| G5 / P1 | `server/app/api/routes.py:/health`: podía responder 200 aunque la SQLite/schema no estuviera lista, mientras update/restore confiaban en esa ruta. | La dependencia creaba una sesión, pero la función no hacía consulta. | Readiness ahora ejecuta `SELECT 1 FROM jobs LIMIT 1`; error SQLAlchemy devuelve 503 genérico sin filtrar detalle. | `test_health_no_disponible_si_sqlite_no_esta_lista` y caso normal; suite servidor **60/60 pass**. No es liveness separado. |
| G6 / P1 | `server/app/services/queue_service.py:reprint` y `server/app/api/routes.py`: un job archivado podía duplicarse hacia impresora inactiva cuyo destino ya se anonimizó. | `reprint` copiaba `printer_id` y payload sin revisar estado/actividad del destino. | Servicio rechaza destino faltante, inactivo o archivado; API devuelve 409 y no crea nuevo job. | `test_reprint_de_impresora_archivada_rechazado`; suite servidor **60/60 pass**. |
| G7 / P1 | `server/app/services/queue_service.py:enqueue`: colisión simultánea de clave podía escapar como 500/SQLite locked. | Lookup previo no serializa requests; constraint unique resuelve carreras al insertar y WAL puede producir `SQLITE_BUSY_SNAPSHOT`. | Alta/evento dentro de savepoint; captura de `IntegrityError` devuelve el ganador compatible o conflicto; ante `OperationalError` se revierte snapshot y se consulta el ganador; API retorna 503 si no hay ganador confirmado para que cliente reintente con la misma clave. No se afirma exactly-once. | `test_idempotencia_resuelve_colision_sqlite_a_job_ganador` simula lock y ganador persistido; suite servidor **60/60 pass**. Stress multiproceso real pendiente. |
| G8 / P2 | `server/app/services/queue_service.py:claim_next`: el estado `processing` podía persistir sin su `JobEvent`. | UPDATE del claim se confirmaba por conexión directa y evento se insertaba después vía ORM. | UPDATE y evento `pending→processing` ahora comparten una única transacción SQLAlchemy Core. | Regresión en `test_claim_no_duplica_con_current_session` consulta el evento inmediatamente; suite servidor **60/60 pass**. Crash/stress de workers pendiente. |
| G9 / P2 | `deploy/scripts/demo_walkthrough.sh`: DB, cookie de sesión y logs quedaban en rutas predecibles/persistentes bajo `/tmp`. | Nombres fijos para cookie/logs y trap que solo detenía procesos. | `umask 077`, directorio único 0700, cookie/logs bajo ese directorio y eliminación por defecto al salir; `LBA_DEMO_KEEP=1` preserva voluntariamente el directorio privado. | Regresión estática `test_walkthrough_uses_private_ephemeral_paths_and_cleans_by_default`, además de rechazo remoto/credenciales; suite deploy **22/22 pass**. No se ejecutó walkthrough E2E completo. |
| G10 / P2 | `deploy/proxmox/create_lba_ct.sh`: plantilla local preexistente se reutiliza sin validar identidad/hash. | La comprobación de presencia/lookup en storage no demuestra origen o integridad criptográfica. | Pendiente: consumir hash firmado/confiable del catálogo/repositorio de Proxmox o exigir checksum confiable configurado y validarlo antes de `pct create`. No se inventa un digest local. | Mock solo prueba reuso/no-download y fallo de descarga; no prueba contenido/hash ni Proxmox real. **Pendiente**. |
| G11 / P2 | `odoo_addons/lba_print_connector/static/src/app/pos_store_patch.js`: failover no cubre impresora primaria activa pero offline; la primera impresora activa según `_order=name,id` es primaria. | `canFailoverPrinter` limita fallback a rechazo explícito `printer_unavailable` sin job; timeout/excepción podría ser ambiguo y reintentar en otra impresora duplicaría salida. | Conservado por seguridad; no cambiar sin protocolo para resolver aceptación idempotente entre servidores. Documentar/configurar explícitamente la primaria sigue pendiente. | Node prueba solo rechazo explícito (`2 archivos pass`); no prueba OWL/browser, impresora offline ni E2E. **Parcial / pendiente de runtime**. |

### Evidencia reproducible y atribución

- La evidencia local de esta tabla se ejecutó sobre los cambios fuente que quedaron en los commits QA `47218c3`, `f899670` y `5e4d8dd`; los runs externos listados son de SHA anteriores, no de esos commits.
- Suite servidor reejecutada: `cd server && PYTHONPATH=. .venv/bin/pytest -q` → **60 passed, 46 warnings** (Starlette/httpx y adaptador SQLite/Python 3.12).
- Scripts/Proxmox: `python3 -m unittest discover -s deploy/tests -v` → **22 passed**; incluye `sudo`, mocks y carpetas temporales; Proxmox nunca se contactó.
- Addon: `node --test odoo_addons/lba_print_connector/tests/*.mjs` → **2 archivos passed**; `compileall` y AST Python: **55 archivos**; parseo XML: **11 archivos**. No hay runtime Odoo, por lo que TransactionCase no se ejecutó.
- Estáticos reejecutados: `bash -n` → **8 scripts OK**; YAML de **2 workflows** parseado con PyYAML instalado en `/tmp` (sin editar dependencias del repo); `git diff --check` OK. Scripts ejecutables mantienen modo 0755; `lib_common.sh` es biblioteca y modo 0644.
- CI externo leído por `gh`: [server run 45239085620](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45239085620), [Odoo run 45239085651](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45239085651), ambos `success` en `7ae0857...` únicamente.
- El empaquetador fue comparado dos veces en el SHA base; no genera artefactos desde un checkout sucio por diseño. Los paquetes de QA finales dependen de commit limpio y workflows nuevos.


## Addendum de evidencia CI y artefactos QA — 2026-11-23

Este addendum es la fuente vigente para el estado de CI y empaquetado; los estados anteriores de E2/E3/E5/E7 y de C1/C2/C4/C5 deben leerse como capturas previas. Los workflows aquí citados prueban exactamente el commit de código `49f7249be25e518844de6d7fb5ea427ef08ef7dc` en `fix/odoo19-addon-qa-layouts`. No se modificaron `main` ni `feature/lba-print-foundation`, no se abrió PR y no se desplegó producción.

### Corrección Odoo 19 y resultados

La fuente oficial de Odoo fijada por CI declara `res.users.group_ids` en [res_users.py, commit 62c2f793058de87ff453532f206a96a1e71845d2, líneas 257–259](https://github.com/odoo/odoo/blob/62c2f793058de87ff453532f206a96a1e71845d2/odoo/addons/base/models/res_users.py#L257-L259), no `groups_id`. Se corrigieron los tres fixtures afectados en los tests de departamentos, job y servidor. El test de `action_process_now` se ajustó con `autospec=True` para verificar el recordset seleccionado y el argumento `self`; el método productivo y los controles de acceso no se debilitaron.

| Gate | Run | SHA | Resultado observado |
|---|---|---|---|
| Servidor, despliegue, Node, smoke y empaquetado | [45285525809](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45285525809) | `49f7249be25e518844de6d7fb5ea427ef08ef7dc` | `success`; steps de pytest, deploy, Node, smoke con simulador, build y upload completados. |
| Instalación Odoo, TransactionCase, upgrade y empaquetado | [45285525821](https://github.com/Lean031110/LBA-PrintSystem/actions/runs/45285525821) | `49f7249be25e518844de6d7fb5ea427ef08ef7dc` | `success`; instalación limpia y actualización en una segunda base aislada, cada una con resumen `0 failed, 0 error(s) of 28 tests`. |

Los logs descargados registran 28 líneas `Starting Test` tanto en instalación como en actualización. En ambos, `odoo.tests.result` informa 0 fallos/errores de 28 tests; la línea agregada `odoo.tests.stats` informa 36 tests. Esta discrepancia de conteo se deja explícita y no se interpreta como cobertura adicional. Los `ERROR` SQL de violación de unicidad son provocados por tests dentro de savepoints y el resumen final de Odoo confirma 0 tests fallidos y 0 errores. La ejecución cubre los TransactionCase definidos; no valida el TPV/OWL en navegador ni un flujo conectado con LBA.

### Verificación de artefactos

Ambos workflows publicaron `lba-packages-49f7249be25e518844de6d7fb5ea427ef08ef7dc`. Las descargas desde los dos runs tienen manifiesto, TAR y ZIP idénticos byte a byte. `sha256sum -c SHA256SUMS` pasó en cada descarga; se abrieron los dos formatos y se verificaron la raíz `lba_print_connector/`, recursos del módulo, scripts/servicios del servidor y `BUILD-INFO.txt`, que identifica exactamente el SHA anterior. Los hashes son:

| Archivo | SHA-256 |
|---|---|
| `MANIFEST.txt` | `9f609df249f9a77033eae2224457824394b7b79da00277b4bd437a411677ac90` |
| `lba-print-server-debian12-amd64.tar.gz` | `2d2159ab37fb0dcbdaa7bd6ca92dd5c30364558e407596a55b346237723ce1cd` |
| `lba_print_connector-19.0.1.0.0.zip` | `99b9ee38541ac2ac1911c3e7100328c5ee173eb7256b84fc6c346000006a5147` |

Comprobaciones reproducibles localmente para este corte: suite servidor **60 passed, 46 warnings**; suite deploy **22 passed**; Node **2/2 passed**; manifest declara 12 recursos existentes, AST de tests Python y parseo XML pasaron, `git diff --check` pasó tras la actualización documental. El TAR/ZIP son artefactos de QA; no se instalaron en un LXC Debian 12 ni se publicaron como release.

### Reevaluación de hallazgos tocados por este run

| Hallazgo | Estado actualizado | Evidencia y límite |
|---|---|---|
| C1 — autorización/ACL de creación POS | Parcial con TransactionCase verificado | El test de creación directa por POS user y POS manager pasó en las dos ejecuciones de 28 tests. El flujo autorizado vía navegador TPV y E2E sigue pendiente. |
| C2 — acción manual de procesamiento | Parcial con TransactionCase verificado | La prueba de manager y despacho limitado a registros seleccionados pasó; petición HTTP real en la integración Odoo↔LBA no se ejecutó. |
| C4 — reconciliación de 409 | Parcial con TransactionCase verificado | Casos con respuesta sin job y con ID sin status pasaron; el transporte remoto está mockeado, no es E2E. |
| C5 — acciones ACL de servidor | Parcial con TransactionCase verificado | La regresión de usuario POS solo lectura pasó; validación visual de menús/acciones y permisos en navegador queda pendiente. |
| E2/E3 — pipeline y pin upstream Odoo | Corregido/verificado para este workflow | CI instala dependencias, usa el upstream SHA fijo y completó instalación más upgrade en PostgreSQL 16. No demuestra soporte en otras combinaciones de plataformas. |
| E5 — empaquetado | Parcial, gate de artefactos QA superado | Builds de dos workflows idénticos, hashes y contenido verificados; faltan instalación desde paquete en Debian/LXC real, descarga por usuario y proceso de release. |
| E7 — atribución CI a SHA | Corregido para el commit citado | Ambos runs concluyeron `success` y registran el mismo SHA `49f7249...`; los runs anteriores citados en secciones históricas no se reutilizan como evidencia de este SHA. |

### Gates que continúan pendientes

No se ejecutaron navegador OWL/TPV, Playwright, integración E2E Odoo→LBA→worker→impresora virtual, stress de varios procesos/claims, caída entre `sendall` y commit, instalación/actualización/reinicio en LXC Debian 12 con systemd real, `systemd-analyze verify` en ese entorno, bloqueo de egress para probar offline, revisión efectiva de TLS/SAN/cookie `Secure`/firewall, ni pruebas físicas autorizadas. Tampoco se accedió a la base de datos de Lo D’ Leo, se hizo escaneo LAN o se enviaron comandos a impresoras. No se declara que `sent` signifique papel impreso, no se integra en `main` y no se publica una release estable.

## Addendum — instalación limpia, matriz Linux, impresora virtual, E2E de navegador y estrés (2026-11-25)

Esta sección documenta la ampliación de CI y la evidencia ejecutada **hoy** en el sandbox de trabajo. Las secciones y addenda anteriores describen cortes previos; aquí se agrega cobertura nueva y se corrigen dos defectos encontrados al construirla. Nada de esto es una aprobación de producción.

### Qué se agregó

| Flujo / archivo | Propósito |
|---|---|
| `.github/workflows/ci-server.yml` → job `clean-package-install` | Construye el `tar.gz`, lo descomprime en un directorio temporal ajeno al checkout y ejecuta `deploy/scripts/verify_clean_install.sh`: venv nuevo, `pip install -r server/requirements.txt`, `pip check`, `init_db()`, `import app.main`, arranque real de uvicorn con `/api/v1/health` y `python -m app.worker --once`. Detecta archivos olvidados en el paquete y dependencias no declaradas. |
| `.github/workflows/ci-install-matrix.yml` → job `clean-package` | Instala el paquete en contenedores **Debian 12, Ubuntu 22.04, Ubuntu 24.04 y Xubuntu 24.04** (Ubuntu + XFCE). Xubuntu comparte base y repositorios con Ubuntu LTS, por lo que se reproduce el escritorio XFCE en lugar de una ISO distinta. |
| `.github/workflows/ci-install-matrix.yml` → job `systemd-install` | Ejecuta el `deploy/scripts/install.sh` real como root dentro de un contenedor privilegiado con **systemd como PID 1** (`deploy/ci/systemd/Dockerfile`), en Debian 12 y Ubuntu 24.04. Valida unidades habilitadas/activas, permisos, healthcheck, impresión a través de la cola, reinicio de la API y reinstalación idempotente (`deploy/ci/test_systemd_install.sh`). |
| `.github/workflows/ci-stress.yml` | Tres escenarios de estrés con impresoras virtuales y workers reales: 300 trabajos/3 workers/3 impresoras; 150/1/1; y ráfaga de idempotencia de 80 claves × 16 envíos simultáneos. |
| `deploy/scripts/stress_test.py` | Envío concurrente, verificación de 202/409 exactos, drenaje de cola, `sent` para todos, un documento por trabajo con SHA-256 válido, ausencia de claves duplicadas y `PRAGMA integrity_check`. Genera informe JSON con latencias y throughput. |
| `.github/workflows/ci-odoo-browser-e2e.yml` + `deploy/ci/odoo_browser_e2e.py` | Instala Odoo 19 (commit fijo), el addon, PostgreSQL 16, el servidor LBA, un worker y una **impresora virtual**, y opera Chromium con Playwright: login, lista de impresoras, «Probar conexión», «Sincronizar impresoras», «Impresión de prueba» → «Enviar a la impresora». El éxito exige un trabajo `sent` y un documento escrito por la impresora virtual. |
| `deploy/ci/odoo_seed_e2e.py` | Siembra el usuario admin, el registro `lba.print.server` con el token, ejecuta conexión/sincronización y asigna la impresora a las plantillas. |
| `server/app/drivers/simulator.py --save-dir` | **Impresora virtual con papel en disco**: por cada documento recibido escribe `document-NNNN-<sha>.escpos.bin` (bytes exactos), `.txt` (reconstrucción legible) y una línea en `documents.jsonl` con hash, tamaño y hora. Es la validación de que la impresión llegó al destino, sin hardware. |
| `server/tests/test_virtual_printer.py` | Regresiones del papel virtual y del parser de preview. |

### Evidencia local (sandbox, sin Docker)

- Suite del servidor: `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q` → **62 passed, 46 warnings** (60 previos + 2 nuevos). Los warnings son los mismos Starlette/httpx y SQLAlchemy/SQLite ya documentados; no son fallos.
- Instalación limpia real desde el paquete: paquete construido desde un snapshot limpio del árbol (`16184c3...`) y `bash deploy/scripts/verify_clean_install.sh …` → **CLEAN INSTALL OK**: sin requisitos rotos, BD/tablas creadas, credenciales y `secret_key` en modo 0600, `/api/v1/health` con solo las cuatro claves públicas y worker `--once` correcto.
- Estrés local: `deploy/scripts/stress_test.py --jobs 300 --duplicates 30 --burst 10 --concurrency 24 --workers 3 --printers 3` → 600 peticiones (330 `202` + 270 `409`), **330 documentos** con hash único, `integrity_check=ok`, ~284 req/s de admisión y ~90 trabajos/s de drenaje; p50 68.8 ms / p95 136.1 ms. También pasó el escenario 120/2/2 y 140 trabajos únicos.
- Sintaxis: `bash -n` en los scripts nuevos y modificados, `py_compile` de los scripts de CI y **parseo YAML de los 5 workflows** → OK.

### Resultados reales en GitHub Actions

Los workflows se ejecutaron sobre el PR en borrador [#1](https://github.com/Lean031110/LBA-PrintSystem/pull/1) (el `workflow_dispatch` no está disponible hasta que el workflow exista en la rama por defecto). En el commit final `85905f3` **pasan todos los jobs**:

| Workflow / job | Resultado |
|---|---|
| `CI LBA Print Server` → `Servidor — API, cola, rendering, simulador` | ✅ pytest, suite de despliegue, tests Node, smoke E2E y paquetes |
| `CI LBA Print Server` → `Servidor — instalar el tar.gz en un venv limpio` | ✅ deps + `init_db` + `import app.main` sobre el paquete descomprimido |
| `CI instalación Linux` → paquete limpio en **Debian 12**, **Debian 13**, **Ubuntu 24.04** y **Xubuntu 24.04** | ✅ instalación limpia en contenedor para las cuatro imágenes |
| `CI instalación Linux` → `install.sh` con **systemd real** en **Debian 12** y **Ubuntu 24.04** | ✅ unidades activas, healthcheck, impresión por la cola, reinicio y reinstalación idempotente |
| `CI estrés y concurrencia` → 300/3/3, 150/1/1 y ráfaga 80×16 | ✅ 3 jobs verdes (documentos, hashes, `integrity_check`) |
| `CI Odoo 19 — LBA Print Connector` | ✅ instalación limpia, TransactionCase y actualización del addon |
| `CI Odoo 19 — E2E de navegador` | ✅ Odoo 19 + addon + Chromium: login, lista de impresoras, «Probar conexión», sincronización, vista previa, «Impresión de prueba» → trabajo `sent` + documento escrito por la impresora virtual |

Tiempos observados en el runner: matriz de distros ~25–45 s por job; systemd ~35 s; estrés ~10 s por escenario; E2E de navegador ~6 min (clonado de Odoo, pip y Chromium incluidos).

### Defectos encontrados por los flujos nuevos y corregidos

1. `preview.render_preview` entraba en **bucle infinito** ante un comando `ESC` desconocido; ahora consume el comando y hay test de regresión.
2. `install.sh` comprobaba la salud una sola vez tras 2 s; ahora espera readiness hasta 60 s y falla con diagnóstico.
3. **`umask 077` en `install.sh`** dejaba `/opt/lba/server/.venv` en `0700 root:root`: `init_db` como usuario `lba` fallaba con `Permission denied` y el servicio no habría podido ejecutar su intérprete. El umask restrictivo queda solo para el log; el árbol se instala con `022` y el test systemd verifica que `lba` ejecuta el venv.
4. **Ubuntu 22.04 no es soportado**: trae Python 3.10 y `sqlalchemy>=2.1`/FastAPI actual exigen ≥ 3.11. Se retiró de la matriz, se añadió Debian 13 y tanto `install.sh` como `verify_clean_install.sh` abortan con un mensaje explícito en lugar de un error de pip.
5. El E2E hacía `mkdir` sobre variables de `$GITHUB_ENV` en el mismo step que las definía (`mkdir: cannot create directory ''`).
6. **El asistente de «Impresión de prueba» fallaba con `AccessError`** para usuarios TPV: `lba.print.job.create` bloquea a los usuarios POS y el asistente no usaba `sudo()` aunque el documento lo genera el servidor. Corregido y cubierto por el E2E de navegador.
7. El test de systemd usaba `sudo` (no instalado en la imagen base) y luego importaba `app.main` sin cargar `lba-print.env` ni el directorio de trabajo de la unidad; ahora usa `runuser` y replica el entorno del servicio.

### Límites explícitos de esta evidencia

1. La matriz valida **contenedores** `debian:12`, `debian:13`, `ubuntu:24.04` y `ubuntu:24.04` + XFCE (aproximación a Xubuntu: misma base y repositorios, sin la ISO de escritorio completa). No se probó una instalación de escritorio real ni un arranque gráfico.
2. La instalación con systemd corre en un contenedor privilegiado con systemd como PID 1; valida unidades, permisos, servicios y reinstalación, pero **no** un LXC de producción, un reinicio del host ni el firewall/red reales.
3. Solo arquitectura `x86_64`. No se cubren Fedora/RHEL/Arch: `install.sh` exige `apt-get` + systemd Debian/Ubuntu.
4. La impresora virtual demuestra que los bytes llegaron a un socket y se materializaron como documento (`*.escpos.bin`, `*.txt`, `documents.jsonl`); **no** demuestra impresión térmica, legibilidad física, corte ni calibración. `sent` sigue significando «bytes transmitidos», no papel impreso.
5. El E2E de navegador depende del DOM y de los xmlid de Odoo 19 en el commit fijado; un cambio de Odoo puede romper selectores. Se ejecutó una sola vez verde, no de forma repetida contra varias versiones.
6. Las pruebas de estrés usan SQLite/WAL y procesos locales en el runner; no modelan disco lleno, red lenta, cortes de energía ni caída entre `sendall` y commit. No se afirma exactly-once.
7. El PR sigue en **borrador** y no se ha fusionado a `main`; no hay release ni despliegue. No se ejecutaron pruebas físicas ni se contactó la base ni la LAN de Lo D’ Leo.
