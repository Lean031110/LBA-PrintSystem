# Referencias técnicas de Odoo 19 POS

Este documento conserva las referencias upstream usadas para auditar el punto de extensión del addon `lba_print_connector`. Se consultó el árbol `19.0` de Odoo; las referencias remotas pueden avanzar con esa rama. La integración aún debe instalarse y ejecutarse en CI sobre una instancia real de Odoo 19 antes de considerarse verificada.

## Flujo de impresión POS

- `PosStore.printReceipt()` entrega el recibo al servicio nativo y actualiza `nb_print` solo cuando el resultado de impresión es satisfactorio. El parche LBA mantiene esa semántica y conserva `super.printReceipt()` si LBA no está habilitado: [servicio PosStore de Odoo 19](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/point_of_sale/static/src/app/services/pos_store.js).
- `PosStore.printChanges()` genera los documentos de cocina a partir de `generateOrderChange()` y `filterChangeByCategories()`. El filtro se basa en las categorías POS de los productos, y el flujo nativo maneja impresoras y reintentos. El parche LBA consume el mismo generador, omite deltas vacíos y llama a `super.printChanges()` para impresoras Odoo nativas: [servicio PosStore de Odoo 19](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/point_of_sale/static/src/app/services/pos_store.js).
- `pos.printer` es un modelo cargado por POS. Sus campos del frontend se declaran en `_load_pos_data_fields()` y sus categorías en `product_categories_ids`: [modelo pos.printer de Odoo 19](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/point_of_sale/models/pos_printer.py).
- La lista de modelos que se carga en una sesión se determina en `pos.session._load_pos_data_models()`. Los modelos LBA que el frontend necesita se agregan a esa lista y usan `pos.load.mixin`: [modelo pos.session de Odoo 19](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/point_of_sale/models/pos_session.py) y [pos.load.mixin de Odoo 19](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/point_of_sale/models/pos_load_mixin.py).
- Cuando el POS limita categorías, el core deriva su dominio de las categorías de sus impresoras nativas y de categorías disponibles. La extensión LBA amplía ese dominio con las categorías asignadas a departamentos LBA de la compañía: [modelo pos.category de Odoo 19](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/point_of_sale/models/pos_category.py).

## Decisiones implementadas a partir de estas referencias

El ruteo LBA se toma de `lba.print.department.category_ids` y `printer_ids`, no de un campo ficticio en `pos.printer`. Las categorías no asignadas no llegan a impresoras LBA salvo que exista un departamento activo con `is_fallback=True`; el ruteo se filtra después de aplicar el generador del core. Una jerarquía de categorías padre/hija asignada a departamentos distintos se rechaza para evitar impresiones duplicadas.

La confirmación del servidor de impresión no equivale a salida física. En Odoo, `pending` significa que el trabajo quedó guardado localmente; `queued` significa que LBA lo aceptó; `sent` significa que el servidor transmitió bytes al socket, sin sensor ni acuse que confirme papel impreso. Las consultas de hardware y validaciones físicas siguen pendientes.
