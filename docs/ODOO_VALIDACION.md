# VALIDACIÓN del addon en TU instancia local de Odoo 19 (+ CI opcional)

> Este sandbox no alcanza tu LAN: el addon se entrega con tests automatizados
> (mocks de HTTP) y este checklist de validación manual. Síguelo en orden y
> registra cualquier desviación en un issue del repo.

## A) Tests automatizados dentro de Odoo (tu host)

```bash
# dentro del host Odoo, con acceso al addon en addons-path:
$ odoo-bin -c /etc/odoo/odoo.conf -d test_lba \
    -i lba_print_connector --test-tags /lba_print_connector \
    --stop-after-init --http-port=8099
```
Cubre: conexión/sincronización con HTTP mockeado, estados de la cola
(`pending→sent`, reintentos, agotamiento), idempotencia (409 + clave única),
payloads inválidos, departamentos por defecto y constraint de código.

## B) Checklist manual end-to-end (12 pasos)

1. **Arranca LBA** (LXC o dev): `deploy/scripts/install.sh` → panel en
   `http://<lba>:8000`, login admin.
2. **Simulador**: `systemctl start lba-print-simulator` (impresora falsa
   127.0.0.1:9910) o una Rongta/Xprinter real de tu LAN.
3. **Panel → Dispositivos**: registra la impresora (IP/puerto/80mm/CP850).
4. **Panel → Prueba de impresión → "Caracteres"**: valida `ñ áéíóú ¿¡`
   (cambia encoding si sale basura; ver docs/COMPATIBILITY.md §5).
5. **Panel → Seguridad**: crea token "odoo-produccion" y cópialo.
6. **Odoo**: instala `lba_print_connector` (apps → "LBA Print Connector").
7. **Odoo → LBA Print → Servidor**: URL `http://<lba>`, puerto 8000, token →
   **Probar conexión** (estado "Conectado") → **Sincronizar impresoras**.
8. **Odoo → LBA Print → Departamentos**: asigna impresoras a Caja/Cocina/
   Pizzería/Bar/Salón y categorías POS si quieres segmentar.
9. **TPV → Configuración → pestaña "Impresión LBA"**: activa
   "Imprimir por LBA" y elige **impresora de recibos**.
10. **Comandas**: en cada *impresora de comanda* (Ajustes TPV → Impresoras
    de comanda) elige la **Impresora LBA** correspondiente (las categorías
    siguen decidiéndose con el campo nativo).
11. **Pruebas de flujo**: a) validar pago → recibo; b) "Order" → comanda;
    c) añadir 2 unidades y volver a "Order" → delta "NUEVOS: 2 x …";
    d) quitar 1 → delta "CANCELADOS: -1 x …"; e) reimprimir desde el botón
    del TPV; f) con LBA apagado, enviar comanda → el TPV NO se bloquea
    (≤3 s) y al encender LBA el cron imprime lo encolado (Cola de trabajos).
12. **Anti-duplicados**: sincroniza dos TPV con la misma sesión: la misma
    comanda no se imprime dos veces (`last_order_preparation_change` nativo
    + idempotencia `order.uuid+kind+printer`).

## C) GitHub Actions (CI) — dos niveles

1. **Ya incluido** (`.github/workflows/ci-server.yml`): corre los 44 tests
   pytest del servidor + la demo end-to-end con el simulador en cada push.
2. **Opcional para el addon** (manual, experimental): workflow con servicio
   `postgres:16`, `git clone --depth 1 odoo/odoo -b 19.0`,
   `pip install -r odoo/requirements.txt` y
   `odoo-bin -i lba_print_connector --test-tags /lba_print_connector
   --stop-after-init`. Referencias públicas: CI del propio odoo/odoo,
   **OCA QA** (oca/odoo-community repos) y **doodba** de Tecnativa.
   Enfoques alternativos no requeridos por este proyecto.
