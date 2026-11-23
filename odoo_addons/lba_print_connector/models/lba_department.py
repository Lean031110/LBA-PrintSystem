# -*- coding: utf-8 -*-
"""Departamentos de impresión (Caja, Cocina, Pizzería, Bar, Salón, + custom).

Fuente única de verdad del enrutamiento por categorías:
  pos.category → lba.print.department → lba.print.printer(s)

Restricciones:
  - Una categoría POS no puede estar en dos departamentos activos
    (evita asignaciones contradictorias).
  - Departamento "captura sin asignar" (is_fallback): recibe los productos
    cuya categoría no pertenece a ningún otro departamento (opcional).
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
        help="Una o varias impresoras por departamento (v1: imprime en la "
             "primera activa; el resto queda como respaldo)")
    category_ids = fields.Many2many(
        "pos.category",
        "lba_department_pos_category_rel", "department_id", "category_id",
        string="Categorías POS",
        help="Categorías de productos que imprime este departamento. "
             "Una categoría solo puede pertenecer a un departamento activo "
             "(fuente única de verdad del enrutamiento).")
    is_fallback = fields.Boolean(
        "Capturar sin asignar", default=False,
        help="Los productos cuya categoría no pertenece a ningún departamento "
             "se imprimen aquí (p. ej. bebidas nuevas sin categoría asignada). "
             "Solo un departamento activo puede tener esta marca.")
    job_ids = fields.One2many("lba.print.job", "department_id",
                              string="Trabajos")
    job_count = fields.Integer(compute="_compute_job_count")
    template_ids = fields.One2many("lba.print.template", "department_id",
                                   string="Plantillas")
    template_count = fields.Integer(compute="_compute_template_count")

    # Odoo 19: restricción SQL declarada como objeto Constraint (no
    # _sql_constraints, eliminado en 19)
    _code_uniq = models.Constraint(
        "unique(code)", "Ya existe un departamento con ese código")

    def _compute_job_count(self):
        for dept in self:
            dept.job_count = len(dept.job_ids)

    def _compute_template_count(self):
        for dept in self:
            dept.template_count = len(dept.template_ids)

    # ------------------------------------------------------------- validación

    @api.constrains("category_ids", "active")
    def _check_category_unique(self):
        """Una categoría no puede estar en dos departamentos activos.

        La comprobación cruza TODOS los departamentos activos de la DB
        (no solo los registros de la escritura actual).
        """
        for dept in self.filtered("active"):
            for cat in dept.category_ids:
                others = self.search([
                    ("id", "!=", dept.id),
                    ("active", "=", True),
                    ("category_ids", "in", cat.id),
                ])
                if others:
                    raise ValidationError(_(
                        "La categoría \"%(cat)s\" está asignada a los "
                        "departamentos \"%(a)s\" y \"%(b)s\". El enrutamiento "
                        "exige una única asignación por categoría "
                        "(fuente única de verdad).") % {
                            "cat": cat.name,
                            "a": others[0].name,
                            "b": dept.name})

    @api.constrains("is_fallback", "active")
    def _check_single_fallback(self):
        fallbacks = self.search([("is_fallback", "=", True),
                                  ("active", "=", True)]) - self
        if self.filtered("is_fallback").filtered("active") and fallbacks:
            raise ValidationError(_(
                "Solo puede existir un departamento activo con "
                "\"Capturar sin asignar\"."))

    # ---------------------------------------------------------------- consulta

    @api.model
    def resolve_for_categories(self, category_ids):
        """Resuelve el departamento de cada categoría (API estable para
        pruebas y para el frontend).

        :param category_ids: lista de ids de pos.category (con o sin ancestros)
        :return: dict {category_id: department_record} para las categorías
                 que tienen departamento activo asignado.
        """
        result = {}
        for dept in self.search([("active", "=", True)]):
            for cat in dept.category_ids:
                if cat.id not in result:
                    result[cat.id] = dept
        return {cid: dept for cid, dept in result.items()
                if cid in set(category_ids or [])}

    def first_active_printer(self):
        """Primera impresora activa del departamento (v1) o vacío.

        Tolerante con recordsets vacíos (computeds de plantilla sin dept).
        """
        if not self:
            return self.env["lba.print.printer"].browse()
        self.ensure_one()
        return self.printer_ids.filtered(lambda p: p.active)[:1]
