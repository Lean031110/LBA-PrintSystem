# -*- coding: utf-8 -*-
"""Tests de departamentos iniciales y personalizados."""
from odoo.tests.common import TransactionCase


class TestDepartments(TransactionCase):
    def test_departamentos_por_defecto(self):
        codes = set(self.env["lba.print.department"].search([]).mapped("code"))
        for expected in ("caja", "cocina", "pizzeria", "bar", "salon"):
            self.assertIn(expected, codes)

    def test_departamento_custom(self):
        dept = self.env["lba.print.department"].create({
            "name": "Postres", "code": "postres"})
        self.assertTrue(dept.active)
        # código duplicado → constraint
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env["lba.print.department"].create({
                "name": "Postres 2", "code": "postres"})
