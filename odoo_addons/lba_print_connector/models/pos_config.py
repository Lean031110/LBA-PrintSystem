# -*- coding: utf-8 -*-
"""Herencias sobre modelos del core (pos.config).

NO se modifica ningún archivo original de Odoo: solo herencia estándar.

v0.2 — enrutamiento por fuente única de verdad:
  - Se ELIMINA pos.printer.lba_printer_id (doble fuente de verdad con
    lba.print.department): las comandas se enrutan por
    pos.category → lba.print.department → lba.print.printer.
  - pos.config.lba_active + lba_receipt_printer_id: impresión de recibos LBA.
"""
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    lba_active = fields.Boolean(
        "Imprimir por LBA", default=False,
        help="Activa la impresión de recibos y comandas por LBA Print "
             "Server (enrutamiento por departamentos).")
    lba_receipt_printer_id = fields.Many2one(
        "lba.print.printer", string="Impresora de recibos LBA",
        domain=[("active", "=", True)],
        help="Impresora donde se imprimen los recibos de caja (payload "
             "estructurado; LBA genera los bytes ESC/POS).")
    lba_server_id = fields.Many2one(
        "lba.print.server", string="Servidor LBA",
        help="Servidor asociado a esta TPV (para sincronizar/validar).")

    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        for extra in ("lba_active", "lba_receipt_printer_id"):
            if extra not in fields_list:
                fields_list.append(extra)
        return fields_list
