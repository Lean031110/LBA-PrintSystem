# -*- coding: utf-8 -*-
"""Tests de departamentos iniciales y personalizados."""
from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
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
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env["lba.print.department"].create({
                "name": "Postres 2", "code": "postres"})

    def test_categoria_padre_hija_no_se_rutea_a_dos_departamentos(self):
        parent = self.env["pos.category"].create({"name": "Bebidas LBA"})
        child = self.env["pos.category"].create({
            "name": "Café LBA", "parent_id": parent.id})
        self.env["lba.print.department"].create({
            "name": "Bar LBA", "code": "bar-lba",
            "category_ids": [(6, 0, [parent.id])],
        })
        with self.assertRaises(ValidationError):
            self.env["lba.print.department"].create({
                "name": "Cafetería LBA", "code": "cafeteria-lba",
                "category_ids": [(6, 0, [child.id])],
            })
