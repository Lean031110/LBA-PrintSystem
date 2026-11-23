# -*- coding: utf-8 -*-
"""Asistente de vista previa (papel térmico simulado) e impresión de prueba.

La MISMA serialización de plantilla (to_document con sample data) alimenta
la vista previa y la impresión de prueba: lo que se ve es lo que se envía.
"""
from __future__ import annotations

import html as html_mod
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.lba_print_connector.models.lba_template import (
    sample_ticket_data,
)

_logger = logging.getLogger(__name__)

# 96 dpi de pantalla; 0.6 ≈ ancho relativo de un carácter monoespaciado
_MM_TO_PX = 96.0 / 25.4


class LbaPrintPreviewWizard(models.TransientModel):
    _name = "lba.print.preview.wizard"
    _description = "Vista previa / impresión de prueba LBA"

    template_id = fields.Many2one(
        "lba.print.template", required=True, ondelete="cascade")
    mode = fields.Selection(
        [("preview", "Vista previa"), ("test", "Impresión de prueba")],
        default="preview", required=True)
    paper_override = fields.Selection(
        [("auto", "Según impresora de la plantilla"),
         ("58", "Simular 58 mm"),
         ("80", "Simular 80 mm")],
        default="auto", required=True,
        help="Ancho de papel simulado para la vista previa (58/80 mm).")
    printer_id = fields.Many2one(
        "lba.print.printer", string="Impresora de prueba",
        domain=[("active", "=", True)])
    preview_html = fields.Html(
        compute="_compute_preview_html", sanitize=False, readonly=True)
    result_message = fields.Char(readonly=True)

    # ------------------------------------------------------------- vista previa

    @api.depends("template_id", "paper_override")
    def _compute_preview_html(self):
        for wizard in self:
            try:
                wizard.preview_html = wizard._render_paper()
            except Exception as exc:  # noqa: BLE001
                wizard.preview_html = (
                    "<p class='text-danger'>%s</p>" %
                    html_mod.escape(str(exc)))

    def _paper_geometry(self):
        template = self.template_id
        if self.paper_override in ("58", "80"):
            width_mm = int(self.paper_override)
            # columnes típicas del ancho simulado (no se asume 48 para 80)
            columns = {58: 32, 80: 48}[width_mm]
        else:
            width_mm = template.width_mm or 80
            columns = template.columns or 42
        return width_mm, columns

    def _render_paper(self):
        """HTML del papel térmico con los bloques serializados."""
        self.ensure_one()
        template = self.template_id
        data = sample_ticket_data(template.template_type)
        document = template.to_document(data)
        width_mm, columns = self._paper_geometry()
        font_px = round(width_mm * _MM_TO_PX / columns / 0.6, 1)
        char_px = round(width_mm * _MM_TO_PX / columns, 1)

        parts = [(
            "<div class='lba-paper' style='"
            "width:%dmm; font-family: \"DejaVu Sans Mono\", \"Liberation Mono\", "
            "Menlo, Consolas, monospace; font-size:%spx; "
            "background:#fffdf5; color:#111; padding:6px 5px; "
            "box-shadow:0 0 8px rgba(0,0,0,.35); margin:0 auto;'>" %
            (width_mm, font_px))]
        header = (
            "<div style='text-align:center; font-size:11px; color:#666; "
            "margin-bottom:4px;'>%s · %d mm · %d columnas · plantilla «%s»"
            "</div>") % (
            _("Papel térmico simulado"), width_mm, columns,
            html_mod.escape(template.name))
        parts.append(header)
        for block in document["blocks"]:
            parts.append(self._render_block(block, columns, char_px))
        parts.append("</div>")
        return "".join(parts)

    def _render_block(self, block, columns, char_px):
        btype = block["type"]
        if btype == "text":
            style = ["white-space:pre-wrap", "overflow-wrap:break-word",
                     "line-height:1.25", "margin:0"]
            align = block.get("align") or "left"
            style.append("text-align:%s" % align)
            if block.get("bold"):
                style.append("font-weight:700")
            if (block.get("width") or 1) == 2:
                style.append("letter-spacing:%.1fpx" % char_px)
            if (block.get("height") or 1) == 2:
                style.append("font-size:1.7em")
            return "<p style='%s'>%s</p>" % (
                ";".join(style), html_mod.escape(block.get("value", "")))
        if btype == "ruler":
            char = (block.get("char") or "-")[:1]
            return ("<p style='margin:0; white-space:pre; "
                    "overflow:hidden;'>%s</p>" %
                    html_mod.escape(char * columns))
        if btype == "feed":
            return "<p style='margin:0'>&nbsp;</p>" * max(1, block.get("lines", 1))
        if btype == "cut":
            if block.get("feed_before"):
                parts = ["<p style='margin:0'>&nbsp;</p>" *
                         int(block["feed_before"])]
            else:
                parts = []
            parts.append(
                "<div style='border-top:1px dashed #999; margin:4px 0; "
                "text-align:right; color:#999; font-size:10px;'>✂ corte"
                "</div>")
            return "".join(parts)
        if btype == "qr":
            return ("<div style='border:1px solid #444; width:96px; height:"
                    "96px; margin:6px auto; display:flex; align-items:center;"
                    "justify-content:center; color:#888; font-size:10px;'>QR · "
                    "%s</div>" % html_mod.escape(block.get("value", "")[:24]))
        if btype == "barcode":
            return ("<div style='margin:6px 0'><div style='height:40px; "
                    "background:repeating-linear-gradient(90deg,#111 0 2px,"
                    "#fff 2px 5px);'></div><div style='text-align:center;"
                    "font-size:10px; color:#333;'>%s · %s</div></div>" % (
                        html_mod.escape(block.get("symbology", "")),
                        html_mod.escape(block.get("value", "")[:32])))
        if btype == "image":
            return ("<img src='data:image/png;base64,%s' style='display:block;"
                    "margin:4px auto; max-width:100%%;' alt='imagen'/>" %
                    html_mod.escape(block.get("data", "")))
        return ""

    # ---------------------------------------------------------------- acciones

    def action_open_preview(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "lba.print.preview.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "name": _("Vista previa — %s") % self.template_id.name,
        }

    def action_refresh_preview(self):
        return self.action_open_preview()

    def action_send_test_print(self):
        """Impresión de prueba con la MISMA serialización de la vista previa."""
        self.ensure_one()
        template = self.template_id
        printer = self.printer_id or template.printer_id or \
            template.department_id.first_active_printer()
        if not printer:
            raise UserError(_(
                "Selecciona una impresora registrada (o sincroniza "
                "impresoras en el menú Servidor)."))
        if not printer.server_id:
            raise UserError(_("La impresora no tiene servidor LBA asociado."))
        data = sample_ticket_data(template.template_type)
        document = template.to_document(data)  # misma estructura que la previa
        Job = self.env["lba.print.job"]
        key = "test:%s:%s:%d" % (
            template.id, fields.Datetime.now().strftime("%Y%m%d%H%M%S"),
            printer.id)
        job = Job.create({
            "printer_id": printer.id,
            "kind": "test",
            "payload_json": json.dumps(document),
            "order_ref": _("PRUEBA plantilla «%s»") % template.name,
            "department_id": template.department_id.id,
            "idempotency_key": key,
        })
        try:
            job._post_job()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("LBA test print %s: %s", job.uuid, exc)
        state_labels = dict(Job._fields["state"].selection)
        message = (_("Prueba en cola (%s). Estado: %s") %
                   (job.uuid, state_labels.get(job.state, job.state)))
        self.write({"result_message": message})
        return self._notify(message)

    def _notify(self, message: str, kind: str = "success"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": kind, "sticky": False},
        }
