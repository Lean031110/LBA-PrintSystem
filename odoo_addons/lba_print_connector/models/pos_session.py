# -*- coding: utf-8 -*-
"""Carga selectiva de configuración LBA en la sesión POS."""
from odoo import api, models


LBA_POS_MODELS = [
    "lba.print.department",
    "lba.print.printer",
    "lba.print.template",
    "lba.print.template.block",
]


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config):
        models_to_load = super()._load_pos_data_models(config)
        return models_to_load + [
            model for model in LBA_POS_MODELS if model not in models_to_load
        ]
