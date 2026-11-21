# -*- coding: utf-8 -*-
"""Herencias sobre modelos del core (pos.printer, pos.config, pos.category).

NO se modifica ningún archivo original de Odoo: solo herencia estándar.
Campos añadidos al TPV:
  - pos.printer.lba_printer_id: mapea cada impresora de comanda nativa con una
    impresora LBA (las categorías siguen decidiéndose con
    product_categories_ids nativo).
  - pos.config.lba_active + lba_receipt_printer_id: impresión de recibos por LBA.
"""
from odoo import fields, models


class PosPrinter(models.Model):
    _inherit = "pos.printer"

    lba_printer_id = fields.Many2one(
        "lba.print.printer", string="Impresora LBA",
        domain=[("active", "=", True)],
        help="Si se asigna, las comandas de esta impresora se envían por "
             "LBA Print Server en lugar del proxy/IoT. Las categorías se "
             "siguen definiendo arriba (Categorías de productos impresas).")

    # pos.load.mixin: cargar el campo en el frontend del TPV
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if "lba_printer_id" not in fields_list:
            fields_list.append("lba_printer_id")
        return fields_list


class PosConfig(models.Model):
    _inherit = "pos.config"

    lba_active = fields.Boolean(
        "Imprimir por LBA", default=False,
        help="Activa la impresión de recibos y comandas por LBA Print Server.")
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
