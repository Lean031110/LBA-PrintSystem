# -*- coding: utf-8 -*-
"""Extensión de la carga de categorías para departamentos LBA."""
from odoo import api, models
from odoo.fields import Domain


class PosCategory(models.Model):
    _inherit = "pos.category"

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = super()._load_pos_data_domain(data, config)
        if not config.limit_categories:
            return domain
        departments = self.env["lba.print.department"].search([
            ("active", "=", True),
            ("printer_ids.server_id.company_id", "=", config.company_id.id),
        ])
        lba_category_ids = departments.category_ids.ids
        if not lba_category_ids:
            return domain
        return Domain.OR([domain, [("id", "in", lba_category_ids)]])
