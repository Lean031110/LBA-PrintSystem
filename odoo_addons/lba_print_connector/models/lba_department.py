# -*- coding: utf-8 -*-
"""Departamentos de impresión (Caja, Cocina, Pizzería, Bar, Salón, + custom)."""
from odoo import fields, models


class LbaPrintDepartment(models.Model):
    _name = "lba.print.department"
    _description = "Departamento de impresión LBA"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help="caja / cocina / pizzeria / bar / "
                                           "salon / personalizados")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    printer_ids = fields.Many2many(
        "lba.print.printer",
        "lba_department_printer_rel", "department_id", "printer_id",
        string="Impresoras",
        help="Una o varias impresoras por departamento (reparto round-robin "
             "no implementado en v1: imprime la primera activa)")
    category_ids = fields.Many2many(
        "pos.category",
        "lba_department_pos_category_rel", "department_id", "category_id",
        string="Categorías POS",
        help="Categorías de productos que imprime este departamento "
             "(en adición a las categorías de cada pos.printer nativo)")
    job_ids = fields.One2many("lba.print.job", "department_id",
                              string="Trabajos")
    job_count = fields.Integer(compute="_compute_job_count")

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Ya existe un departamento con ese código"),
    ]

    def _compute_job_count(self):
        for dept in self:
            dept.job_count = len(dept.job_ids)
