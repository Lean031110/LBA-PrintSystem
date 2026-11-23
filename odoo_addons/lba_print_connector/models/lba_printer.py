# -*- coding: utf-8 -*-
"""Impresoras sincronizadas desde el LBA Print Server."""
from odoo import api, fields, models


class LbaPrintPrinter(models.Model):
    _name = "lba.print.printer"
    _description = "Impresora LBA (sincronizada desde el servidor)"
    _inherit = ["pos.load.mixin"]
    _order = "name, id"
    _rec_names_search = "name,external_id,ip"

    server_id = fields.Many2one("lba.print.server", required=True,
                                ondelete="cascade", string="Servidor")
    external_id = fields.Char("ID externo", required=True, index=True,
                              help="UUID del registro en LBA Print Server")
    name = fields.Char(required=True)
    manufacturer = fields.Char()
    model = fields.Char()
    ip = fields.Char(string="IP")
    port = fields.Integer(default=9100)
    connection_type = fields.Char(default="network")
    protocol = fields.Char(default="escpos_raw_tcp")
    paper_width_mm = fields.Integer(default=80)
    columns = fields.Integer(default=48)
    encoding = fields.Char(default="CP850")
    status = fields.Char(default="unknown", help="unknown/online/offline")
    notes = fields.Char()
    active = fields.Boolean(default=True)
    department_ids = fields.Many2many(
        "lba.print.department",
        "lba_department_printer_rel", "printer_id", "department_id",
        string="Departamentos")
    job_ids = fields.One2many("lba.print.job", "printer_id",
                              string="Trabajos")

    _server_external_uniq = models.Constraint(
        "unique(server_id, external_id)",
        "Esa impresora ya está sincronizada en este servidor",
    )

    def _load_pos_data_fields(self, config):
        return ["id", "name", "external_id", "server_id", "active",
                "department_ids", "paper_width_mm", "columns"]

    @api.model
    def _load_pos_data_domain(self, data, config):
        receipt_id = config.lba_receipt_printer_id.id or 0
        return ["&", ("active", "=", True), "|",
                ("server_id.company_id", "=", config.company_id.id),
                ("id", "=", receipt_id)]
