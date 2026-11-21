# -*- coding: utf-8 -*-
{
    "name": "LBA Print Connector",
    "summary": "Impresión térmica para Odoo 19 vía LBA Print Server (red local, sin IoT)",
    "description": """
Conecta el TPV de Odoo 19 Community (recibos y comandas de pos_restaurant)
con LBA Print Server (FastAPI + python-escpos) en la red local.

- Impresión de recibo tras validar el pago (patch de PosStore.printReceipt).
- Comandas al enviar el pedido, con deltas de modificación/cancelación
  (patch de PosStore.printChanges reutilizando generateOrderChange).
- Cola de salida persistente (lba.print.job) con reintentos por cron:
  el TPV nunca se bloquea si el servidor LBA no responde.
- Sin IoT Box, sin Docker, sin API externa JSON-2 de Odoo.
    """,
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "author": "LBA",
    "license": "MIT",
    "depends": ["point_of_sale", "pos_restaurant"],
    "data": [
        "security/ir.model.access.csv",
        "security/lba_security.xml",
        "views/lba_menus.xml",
        "views/lba_server_views.xml",
        "views/lba_printer_views.xml",
        "views/lba_department_views.xml",
        "views/lba_job_views.xml",
        "views/pos_config_views.xml",
        "data/lba_departments.xml",
        "data/ir_cron.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "lba_print_connector/static/src/app/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
