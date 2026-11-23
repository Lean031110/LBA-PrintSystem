# -*- coding: utf-8 -*-
"""Plantillas de impresión visual (diseñador de tickets).

Modelos:
  - lba.print.template: cabecera de la plantilla (tipo, ámbito, prioridad).
  - lba.print.template.block: bloques ordenados que componen el ticket.

Seguridad del contenido: los "campos dinámicos" son una LISTA BLANCA
(field_key). NO se permite Python, JS, Jinja, expresiones arbitrarias ni
HTML del usuario: el serializador solo emite bloques primitivos
(text/ruler/qr/barcode/image/feed/cut) que LBA Print Server ya sabe
renderizar. El MISMO serializador alimenta la vista previa (papel térmico),
la impresión de prueba y la impresión real desde el TPV.
"""
from __future__ import annotations

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

MAX_BLOCKS = 200

#: Campos dinámicos permitidos (lista blanca). Nada más se evalúa jamás.
FIELD_WHITELIST = [
    ("company.name", "Empresa · Nombre"),
    ("company.address", "Empresa · Dirección"),
    ("order.ref", "Pedido · Referencia (preparationName)"),
    ("order.cashier", "Pedido · Camarero"),
    ("order.table", "Pedido · Mesa"),
    ("order.customer_count", "Pedido · Comensales"),
    ("order.datetime", "Pedido · Fecha y hora"),
    ("order.subtotal", "Pedido · Subtotal"),
    ("order.discount", "Pedido · Descuento"),
    ("order.total", "Pedido · Total"),
    ("order.change", "Pedido · Cambio"),
    ("order.note", "Pedido · Nota general del cliente"),
    ("department.name", "Departamento · Nombre"),
]

#: Tablas permitidas (bloques "table"): filas de líneas/pagos ya formateadas.
TABLE_WHITELIST = [
    ("lines.new", "Líneas · Nuevas (comanda)"),
    ("lines.cancelled", "Líneas · Canceladas (comanda)"),
    ("lines.all", "Líneas · Todas (recibo)"),
    ("payments.list", "Pagos · Métodos e importes"),
]

#: Condiciones permitidas para bloques condicionales (lista blanca).
CONDITION_WHITELIST = [
    ("order.has_table", "El pedido tiene mesa"),
    ("order.has_note", "El pedido tiene nota del cliente"),
    ("order.has_change", "Hay cambio (vuelto)"),
    ("order.has_payments", "Hay líneas de pago"),
    ("order.is_bill", "Es pre-cuenta (bill antes de pagar)"),
    ("order.is_reprint", "Es reimpresión"),
    ("order.has_cancelled", "Hay líneas canceladas"),
]

BLOCK_TYPES = [
    ("text", "Texto fijo"),
    ("field", "Campo dinámico"),
    ("ruler", "Línea separadora"),
    ("ruler_double", "Línea doble"),
    ("spacer", "Espaciado (líneas en blanco)"),
    ("feed", "Avance de papel"),
    ("cut", "Corte de papel"),
    ("qr", "Código QR"),
    ("barcode", "Código de barras"),
    ("image", "Imagen (logo)"),
    ("conditional", "Bloque condicional (con sub-bloques)"),
    ("table", "Tabla de líneas/pagos"),
]

ALIGNMENTS = [("left", "Izquierda"), ("center", "Centro"), ("right", "Derecha")]
SYMBLOGIES = [("CODE128", "Code 128"), ("EAN13", "EAN-13"), ("CODE39", "Code 39")]


def default_blocks_receipt():
    """Bloques por defecto del recibo de caja (espejo del payload JS)."""
    return [
        {"block_type": "field", "field_key": "company.name", "align": "center",
         "bold": True, "size_width": 2, "size_height": 1},
        {"block_type": "field", "field_key": "company.address",
         "align": "center"},
        {"block_type": "field", "field_key": "order.ref", "align": "center"},
        {"block_type": "field", "field_key": "order.cashier"},
        {"block_type": "conditional", "condition_key": "order.has_table",
         "child_blocks": [
             {"block_type": "field", "field_key": "order.table"},
             {"block_type": "field", "field_key": "order.customer_count"},
         ]},
        {"block_type": "ruler", "ruler_char": "="},
        {"block_type": "table", "table_key": "lines.all"},
        {"block_type": "ruler", "ruler_char": "="},
        {"block_type": "field", "field_key": "order.total", "align": "right",
         "bold": True},
        {"block_type": "table", "table_key": "payments.list"},
        {"block_type": "conditional", "condition_key": "order.has_change",
         "child_blocks": [
             {"block_type": "field", "field_key": "order.change"},
         ]},
        {"block_type": "feed", "feed_lines": 3},
        {"block_type": "cut", "cut_feed_before": 0},
    ]


def default_blocks_kitchen():
    """Bloques por defecto de la comanda (espejo del payload JS)."""
    return [
        {"block_type": "text", "value_text": "COMANDA", "align": "center",
         "bold": True, "size_width": 2, "size_height": 1},
        {"block_type": "field", "field_key": "department.name", "align":
         "center", "bold": True},
        {"block_type": "field", "field_key": "order.ref", "bold": True},
        {"block_type": "field", "field_key": "order.cashier"},
        {"block_type": "conditional", "condition_key": "order.has_table",
         "child_blocks": [
             {"block_type": "field", "field_key": "order.table"},
             {"block_type": "field", "field_key": "order.customer_count"},
         ]},
        {"block_type": "field", "field_key": "order.datetime"},
        {"block_type": "ruler", "ruler_char": "="},
        {"block_type": "table", "table_key": "lines.new"},
        {"block_type": "table", "table_key": "lines.cancelled"},
        {"block_type": "feed", "feed_lines": 2},
        {"block_type": "cut", "cut_feed_before": 0},
    ]


def sample_ticket_data(kind="receipt"):
    """Datos de ejemplo para la vista previa y la impresión de prueba.

    Mismo contrato de datos que usa el TPV al serializar un pedido real
    (docs/PRINT_TEMPLATE_DESIGNER.md §Contrato de datos).
    """
    data = {
        "company": {"name": "Lo D' Leo", "address": "Av. Ejemplo 123 · La Habana"},
        "order": {
            "ref": "Orden 00042-001-0001",
            "cashier": "Mitchel",
            "table": "Mesa 7",
            "customer_count": "4",
            "datetime": "2026-11-22 14:05",
            "subtotal": "$ 46.50",
            "discount": "$ 0.00",
            "total": "$ 46.50",
            "change": "$ 3.50",
            "note": "Sin cebolla en una pizza",
            "has_table": True,
            "has_note": True,
            "has_change": kind == "receipt",
            "has_payments": kind == "receipt",
            "is_bill": False,
            "is_reprint": False,
            "has_cancelled": kind == "kitchen",
        },
        "department": {"name": "Cocina"},
        "payments": [
            {"name": "Efectivo", "amount": "$ 50.00"},
        ],
        "lines": {
            "new": [
                {"qty": "2", "name": "Pizza Jamón y Queso", "note": "Extra queso"},
                {"qty": "1", "name": "Ensalada César", "note": ""},
            ],
            "cancelled": [
                {"qty": "1", "name": "Refresco de cola", "note": ""},
            ],
            "all": [
                {"qty": "2", "name": "Pizza Jamón y Queso", "note": ""},
                {"qty": "1", "name": "Ensalada César", "note": ""},
                {"qty": "1", "name": "Refresco de cola", "note": ""},
            ],
        },
    }
    if kind != "receipt":
        data["order"]["total"] = ""
        data["order"]["change"] = ""
        data["order"]["subtotal"] = ""
        data["order"]["discount"] = ""
        data["payments"] = []
    return data


class LbaPrintTemplate(models.Model):
    _name = "lba.print.template"
    _description = "Plantilla de impresión LBA"
    _order = "template_type, sequence, priority, id"

    name = fields.Char(required=True, translate=True)
    template_type = fields.Selection(
        [("receipt", "Recibo de caja"), ("kitchen", "Comanda de cocina")],
        required=True, default="receipt")
    department_id = fields.Many2one(
        "lba.print.department", string="Departamento",
        help="Ámbito: plantilla de comanda para este departamento "
             "(vacío = cualquier departamento sin plantilla propia).")
    printer_id = fields.Many2one(
        "lba.print.printer", string="Impresora",
        help="Ámbito: plantilla preferida para esta impresora (opcional).")
    priority = fields.Integer(
        default=10,
        help="Menor número = mayor preferencia cuando varias plantillas "
             "activas coinciden en ámbito.")
    sequence = fields.Integer(
        default=10,
        help="Orden de listado en el menú de plantillas.")
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(
        default=False, copy=False,
        help="Plantilla de fábrica (se puede restaurar con el botón "
             "\"Restaurar valores por defecto\").")
    width_mm = fields.Integer(
        "Ancho de papel (mm)", compute="_compute_paper", store=True,
        readonly=False,
        help="Ancho real del papel de la impresora de la plantilla "
             "(58/80 mm); se toma del perfil de la impresora, no se asume.")
    columns = fields.Integer(
        "Columnas", compute="_compute_paper", store=True, readonly=False,
        help="Columnas del perfil de la impresora (no se asume 48 para 80mm).")
    block_ids = fields.One2many(
        "lba.print.template.block", "template_id", string="Bloques",
        copy=True, domain=[("parent_id", "=", False)])
    block_count = fields.Integer(compute="_compute_block_count")
    last_modified = fields.Datetime(readonly=True, default=fields.Datetime.now)
    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True)

    _name_company_uniq = models.Constraint(
        "unique(name, company_id)",
        "Ya existe una plantilla con ese nombre",
    )

    @api.depends("printer_id.paper_width_mm", "printer_id.columns",
                 "department_id.printer_ids.paper_width_mm",
                 "department_id.printer_ids.columns")
    def _compute_paper(self):
        for template in self:
            printer = (template.printer_id
                       or template.department_id.first_active_printer())
            template.width_mm = printer.paper_width_mm or 80
            template.columns = printer.columns or 42

    def _compute_block_count(self):
        for template in self:
            template.block_count = len(template.block_ids)

    @api.model
    def resolve_for(self, template_type, department_id=None, printer_id=None):
        """Plantilla activa que aplica: menor prioridad en el ámbito más
        específico (impresora > departamento > general). Determinista."""
        domain = [("template_type", "=", template_type),
                  ("active", "=", True)]
        candidates = self.search(domain)
        dept = int(department_id or 0)
        prn = int(printer_id or 0)
        best = None
        for cand in candidates:
            scope = 0
            if prn and cand.printer_id.id == prn:
                scope = 3
            elif dept and cand.department_id.id == dept:
                scope = 2
            elif not cand.printer_id and not cand.department_id:
                scope = 1
            else:
                continue  # ámbito de otro departamento/impresora: no aplica
            if best is None or (scope, -cand.priority, cand.id) > \
                    (best[0], -best[1].priority, best[1].id):
                best = (scope, cand, cand.id)
        return best[1] if best else self.browse()

    # ------------------------------------------------------------ serializador

    def to_document(self, data):
        """Serializa la plantilla con datos → documento de ticket
        (SOLO bloques primitivos que LBA Print Server sabe renderizar).

        La MISMA estructura alimenta: vista previa, impresión de prueba y
        el TPV real (el JS replica este serializador con datos reales).
        """
        self.ensure_one()
        blocks = []
        for block in self.block_ids.sorted("sequence"):
            blocks.extend(block.to_blocks(data))
        if not blocks:
            raise ValidationError(
                _("La plantilla no tiene bloques que serializar"))
        if len(blocks) > MAX_BLOCKS:
            raise ValidationError(
                _("Demasiados bloques (máx. %d)") % MAX_BLOCKS)
        return {"type": "ticket", "blocks": blocks}

    # ---------------------------------------------------------------- acciones

    def action_preview(self):
        self.ensure_one()
        wizard = self.env["lba.print.preview.wizard"].create(
            {"template_id": self.id, "mode": "preview"})
        return wizard.action_open_preview()

    def action_test_print(self):
        self.ensure_one()
        wizard = self.env["lba.print.preview.wizard"].create(
            {"template_id": self.id, "mode": "test"})
        return {
            "type": "ir.actions.act_window",
            "res_model": "lba.print.preview.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "name": _("Impresión de prueba — %s") % self.name,
        }

    def action_restore_default(self):
        """Restaura los bloques de fábrica de la plantilla (no borra la
        plantilla ni su historial de trabajos)."""
        for template in self:
            template.block_ids.unlink()
            blocks = (default_blocks_receipt() if
                      template.template_type == "receipt"
                      else default_blocks_kitchen())
            template._create_blocks(blocks)
        return self.env["lba.print.preview.wizard"]._notify(
            _("Plantilla restaurada a los valores por defecto"))

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        # Odoo 19 no renombra en copy_data: evita el unique(name, company)
        for template, vals in zip(self, vals_list):
            if "name" in vals and not (default or {}).get("name"):
                vals["name"] = self.env._(
                    "%s (copia)", template.name)
        return vals_list

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        for template, vals in zip(templates, vals_list):
            if not vals.get("block_ids") and not template.block_ids:
                blocks = (default_blocks_receipt() if
                          template.template_type == "receipt"
                          else default_blocks_kitchen())
                template._create_blocks(blocks)
        return templates

    def _create_blocks(self, blocks):
        Block = self.env["lba.print.template.block"]
        for seq, vals in enumerate(blocks, start=10):
            child_blocks = vals.pop("child_blocks", [])
            block = Block.create(dict(vals, template_id=self.id,
                                      sequence=seq * 10))
            for child_seq, child_vals in enumerate(child_blocks, start=10):
                Block.create(dict(child_vals, template_id=self.id,
                                  parent_id=block.id,
                                  sequence=child_seq * 10))
        return True

    def write(self, vals):
        vals["last_modified"] = fields.Datetime.now()
        return super().write(vals)

    def unlink(self):
        # protegemos las de fábrica: se restauran, no se eliminan
        if any(t.is_default for t in self):
            raise ValidationError(_(
                "Las plantillas de fábrica no se pueden eliminar "
                "(desactívalas o restaura sus bloques)."))
        return super().unlink()


class LbaPrintTemplateBlock(models.Model):
    _name = "lba.print.template.block"
    _description = "Bloque de plantilla de impresión LBA"
    _order = "template_id, sequence, id"

    template_id = fields.Many2one(
        "lba.print.template", required=True, ondelete="cascade",
        index=True)
    parent_id = fields.Many2one(
        "lba.print.template.block", string="Bloque condicional padre",
        ondelete="cascade", index=True)
    child_ids = fields.One2many(
        "lba.print.template.block", "parent_id", string="Sub-bloques",
        copy=True)
    sequence = fields.Integer(default=100)
    block_type = fields.Selection(
        BLOCK_TYPES, required=True, default="text")
    display_type = fields.Char(compute="_compute_display_type")

    # --- contenido común
    align = fields.Selection(ALIGNMENTS, default="left")
    bold = fields.Boolean()
    size_width = fields.Integer(default=1)
    size_height = fields.Integer(default=1)

    # --- texto fijo / valor de QR / código de barras
    value_text = fields.Text(
        "Texto fijo / valor",
        help="Texto fijo (tipo texto) o valor literal (QR/código de "
             "barras cuando el origen es 'texto fijo').")

    # --- campo dinámico (lista blanca)
    field_key = fields.Selection(
        FIELD_WHITELIST, string="Campo dinámico",
        help="Solo campos de la lista blanca: nunca expresiones.")
    value_origin = fields.Selection(
        [("fixed", "Texto fijo"), ("field", "Campo dinámico")],
        default="fixed", required=True,
        help="Origen del valor para QR y códigos de barras.")

    # --- reglas / espaciados
    ruler_char = fields.Char(default="-", size=1)
    spacer_lines = fields.Integer(default=1)
    feed_lines = fields.Integer(default=1)
    cut_feed_before = fields.Integer(default=0)

    # --- qr / barcode
    qr_size = fields.Integer(default=6)
    symbology = fields.Selection(SYMBLOGIES, default="CODE128")

    # --- imagen
    image = fields.Image(max_width=384, max_height=192, verify_resolution=True)

    # --- condicional
    condition_key = fields.Selection(
        CONDITION_WHITELIST, string="Condición")

    # --- tabla
    table_key = fields.Selection(
        TABLE_WHITELIST, string="Tabla")

    # ------------------------------------------------------------------ validez

    @api.depends("block_type")
    def _compute_display_type(self):
        labels = dict(BLOCK_TYPES)
        for block in self:
            block.display_type = labels.get(block.block_type, "")

    @api.constrains("block_type", "field_key", "value_text",
                    "condition_key", "table_key", "parent_id")
    def _check_block(self):
        for block in self:
            btype = block.block_type
            if btype == "field" and not block.field_key:
                raise ValidationError(
                    _("El bloque de campo dinámico necesita un campo "
                      "de la lista blanca."))
            if btype == "text" and not (block.value_text or "").strip():
                raise ValidationError(
                    _("El bloque de texto fijo no puede estar vacío."))
            if btype == "conditional" and not block.condition_key:
                raise ValidationError(
                    _("El bloque condicional necesita una condición "
                      "de la lista blanca."))
            if btype == "table" and not block.table_key:
                raise ValidationError(
                    _("El bloque de tabla necesita una tabla "
                      "(líneas/pagos) de la lista blanca."))
            if btype != "conditional" and block.child_ids:
                raise ValidationError(
                    _("Solo los bloques condicionales tienen sub-bloques."))
            if btype == "conditional" and block.parent_id:
                raise ValidationError(
                    _("Los bloques condicionales no se pueden anidar "
                      "(máx. un nivel)."))
            if btype in ("qr", "barcode") and \
                    block.value_origin == "fixed" and \
                    not (block.value_text or "").strip():
                raise ValidationError(
                    _("El bloque QR/código de barras necesita un valor."))
            if btype in ("qr", "barcode") and \
                    block.value_origin == "field" and not block.field_key:
                raise ValidationError(
                    _("El bloque QR/código de barras necesita el campo "
                      "dinámico de la lista blanca."))
            if block.size_width not in (1, 2) or block.size_height not in (1, 2):
                raise ValidationError(
                    _("El tamaño de texto solo admite 1 o 2 "
                      "(doble ancho/alto)."))

    @api.constrains("block_ids")
    def _check_block_count(self):
        for template in self:
            if len(template.block_ids) > MAX_BLOCKS:
                raise ValidationError(_(
                    "La plantilla no puede tener más de %d bloques "
                    "(tiene %d).") % (MAX_BLOCKS, len(template.block_ids)))

    @api.constrains("template_id")
    def _check_template_block_count(self):
        """Límite también al crear bloques directamente (diseñador/datos)."""
        for block in self:
            template = block.template_id
            if template and len(template.block_ids) > MAX_BLOCKS:
                raise ValidationError(_(
                    "La plantilla no puede tener más de %d bloques "
                    "(tiene %d).") % (MAX_BLOCKS, len(template.block_ids)))

    # ------------------------------------------------------------- serializador

    def _text_block(self, value, **extra):
        return {"type": "text", "value": str(value if value is not None else ""),
                "align": self.align or "left",
                "bold": bool(self.bold),
                "width": self.size_width or 1,
                "height": self.size_height or 1, **extra}

    def _resolve_value(self, data):
        if self.value_origin == "field":
            return _field_value(self.field_key, data)
        return self.value_text or ""

    def to_blocks(self, data):
        """Bloques primitivos (text/ruler/qr/barcode/image/feed/cut) de este
        bloque de plantilla con los datos dados."""
        block = self
        btype = block.block_type
        if btype == "text":
            return [block._text_block(block.value_text or "")]
        if btype == "field":
            return [block._text_block(_field_value(block.field_key, data))]
        if btype == "ruler":
            return [{"type": "ruler", "char": block.ruler_char or "-"}]
        if btype == "ruler_double":
            return [{"type": "ruler", "char": "="}]
        if btype == "spacer":
            return [{"type": "feed", "lines": max(1, block.spacer_lines)}]
        if btype == "feed":
            return [{"type": "feed", "lines": max(1, block.feed_lines)}]
        if btype == "cut":
            return [{"type": "cut",
                     "feed_before": max(0, block.cut_feed_before)}]
        if btype == "qr":
            return [{"type": "qr", "value": str(block._resolve_value(data)),
                     "size": max(3, min(11, block.qr_size or 6)),
                     "align": block.align or "center"}]
        if btype == "barcode":
            return [{"type": "barcode", "value": str(block._resolve_value(data)),
                     "symbology": block.symbology or "CODE128",
                     "align": block.align or "center"}]
        if btype == "image":
            if not block.image:
                return []
            return [{"type": "image", "source": "base64",
                     "data": block.image,  # binario Odoo = base64
                     "width": 384, "align": block.align or "center"}]
        if btype == "conditional":
            if _condition_value(block.condition_key, data):
                out = []
                for child in block.child_ids.sorted("sequence"):
                    out.extend(child.to_blocks(data))
                return out
            return []
        if btype == "table":
            rows = _table_rows(block.table_key, data)
            out = []
            for row in rows:
                out.append({"type": "text",
                            "value": row.get("line", ""),
                            "align": "left",
                            "bold": bool(row.get("bold", False)),
                            "width": 1, "height": 1})
            return out
        return []


def _lookup(data, *keys, default=""):
    node = data
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return node if node is not None else default


def _field_value(field_key, data):
    """Valor de un campo de la lista blanca (nunca expresiones)."""
    if not field_key:
        return ""
    if field_key == "company.name":
        return _lookup(data, "company", "name")
    if field_key == "company.address":
        return _lookup(data, "company", "address")
    if field_key == "department.name":
        return _lookup(data, "department", "name")
    if field_key.startswith("order."):
        return _lookup(data, "order", field_key.split(".", 1)[1])
    return ""


def _condition_value(condition_key, data):
    if not condition_key:
        return False
    if condition_key.startswith("order."):
        return bool(_lookup(data, "order", condition_key.split(".", 1)[1]))
    return False


def _table_rows(table_key, data):
    """Filas formateadas de líneas/pagos para bloques tabla (55-58mm)."""
    rows = []
    if table_key in ("lines.new", "lines.cancelled", "lines.all"):
        source = _lookup(data, "lines", table_key.split(".", 1)[1],
                         default=[]) or []
        for line in source:
            qty = line.get("qty", "")
            name = line.get("name", "")
            price = line.get("price", "")
            text_ = f"{qty} x {name}" if qty else name
            if price:
                text_ = f"{text_}  {price}"
            rows.append({"line": text_})
            note = line.get("note", "")
            if note:
                rows.append({"line": f"   » {note}"})
    elif table_key == "payments.list":
        for payment in _lookup(data, "payments", default=[]) or []:
            rows.append({"line": f"{payment.get('name', '')}: "
                                 f"{payment.get('amount', '')}"})
    return rows
