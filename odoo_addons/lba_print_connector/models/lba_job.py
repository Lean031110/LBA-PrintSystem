# -*- coding: utf-8 -*-
"""Cola de salida persistente en Odoo (cuando LBA no responde)."""
from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import uuid as uuidlib
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)

MAX_BLOCKS = 200
MAX_TEXT_CHARS = 4000
MAX_IDEMPOTENCY_KEY_CHARS = 200
MAX_IMAGE_BYTES = 300 * 1024
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_:\-.]+$")
ALLOWED_BLOCKS = {"text", "ruler", "feed", "cut", "qr", "barcode", "image"}

BACKOFF_S = [5, 10, 20, 40, 80, 160, 300]


class LbaPrintJob(models.Model):
    _name = "lba.print.job"
    _description = "Trabajo de impresión LBA (cola de salida)"
    _order = "create_date desc, id desc"

    uuid = fields.Char(required=True, index=True, copy=False, default=False)
    department_id = fields.Many2one("lba.print.department", string="Departamento")
    printer_id = fields.Many2one("lba.print.printer", required=True,
                                 string="Impresora")
    order_ref = fields.Char("Referencia del pedido")
    order_uuid = fields.Char(index=True)
    kind = fields.Selection(
        [("receipt", "Recibo"), ("kitchen", "Comanda"),
         ("delta", "Cambio / cancelación"), ("reprint", "Reimpresión"),
         ("test", "Prueba")], required=True, default="kitchen")
    payload_json = fields.Text(required=True)
    idempotency_key = fields.Char(required=True, index=True)
    state = fields.Selection(
        [("pending", "Pendiente en Odoo"),
         ("queued", "Aceptado por servidor LBA"),
         ("sent", "Bytes transmitidos; sin acuse físico"),
         ("failed", "Fallido"), ("cancelled", "Cancelado")],
        default="pending", required=True, copy=False)
    server_status = fields.Selection(
        [("pending", "Pendiente"), ("processing", "Procesando"),
         ("sent", "Transmitido al socket"), ("failed", "Fallido"),
         ("cancelled", "Cancelado")], readonly=True, copy=False)
    attempts = fields.Integer(default=0)
    max_attempts = fields.Integer(default=5)
    next_attempt = fields.Datetime(default=fields.Datetime.now)
    last_error = fields.Text(readonly=True, copy=False)
    external_job_id = fields.Char(readonly=True, copy=False)
    sent_at = fields.Datetime(
        readonly=True, copy=False,
        help="Hora de transmisión al socket remoto; no verifica la salida física.")
    company_id = fields.Many2one("res.company",
                                 default=lambda s: s.env.company)

    # Odoo 19: _sql_constraints fue eliminado → objetos models.Constraint
    _uuid_uniq = models.Constraint(
        "unique(uuid)", "UUID duplicado")
    _idem_uniq = models.Constraint(
        "unique(idempotency_key)", "Clave idempotente duplicada")

    # ------------------------------------------------------------------ create

    @api.model_create_multi
    def create(self, vals_list):
        # POS users and managers may read their queue, but jobs must be created
        # through the controller that validates the open session, config and
        # printer. The controller calls sudo() only after that validation;
        # RPC callers cannot set env.su through a request context.
        is_pos_user = self.env.user.has_group("point_of_sale.group_pos_user")
        is_pos_manager = self.env.user.has_group("point_of_sale.group_pos_manager")
        if not self.env.su and (is_pos_user or is_pos_manager):
            raise AccessError(_(
                "Los trabajos TPV deben crearse mediante una sesión POS autorizada"))
        for vals in vals_list:
            if not vals.get("uuid"):
                vals["uuid"] = str(uuidlib.uuid4())
            if vals.get("printer_id") and not vals.get("company_id"):
                printer = self.env["lba.print.printer"].browse(
                    vals["printer_id"]).exists()
                if printer and printer.server_id.company_id:
                    vals["company_id"] = printer.server_id.company_id.id
            if not vals.get("idempotency_key"):
                vals["idempotency_key"] = vals["uuid"]
            key = vals["idempotency_key"]
            if not isinstance(key, str) or not key.strip() or \
                    len(key) > MAX_IDEMPOTENCY_KEY_CHARS or \
                    not IDEMPOTENCY_KEY_RE.fullmatch(key):
                raise ValidationError(_("Clave idempotente inválida"))
            try:
                doc = json.loads(vals.get("payload_json") or "{}")
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("El documento no es JSON válido")) from exc
            blocks = doc.get("blocks", []) if isinstance(doc, dict) else []
            if not isinstance(doc, dict) or doc.get("type") != "ticket" or not isinstance(blocks, list) \
                    or not blocks or len(blocks) > MAX_BLOCKS:
                raise ValidationError(
                    _("El documento necesita entre 1 y %d bloques") % MAX_BLOCKS)
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") not in ALLOWED_BLOCKS:
                    raise ValidationError(_("Tipo de bloque inválido"))
                btype = block["type"]
                if btype == "text":
                    if not isinstance(block.get("value", ""), str) or len(
                            block.get("value", "")) > MAX_TEXT_CHARS:
                        raise ValidationError(_("Bloque de texto inválido o demasiado largo"))
                    if block.get("align", "left") not in ("left", "center", "right"):
                        raise ValidationError(_("Alineación de texto inválida"))
                    if block.get("width", 1) not in range(1, 9) or \
                            block.get("height", 1) not in range(1, 9):
                        raise ValidationError(_("Tamaño de texto inválido"))
                elif btype == "feed" and block.get("lines", 0) not in range(0, 21):
                    raise ValidationError(_("Avance de papel inválido"))
                elif btype == "cut" and block.get("feed_before", 0) not in range(0, 21):
                    raise ValidationError(_("Avance previo al corte inválido"))
                elif btype == "ruler" and (not isinstance(block.get("char", "-"), str) or
                                             len(block.get("char", "-")) != 1):
                    raise ValidationError(_("Separador inválido"))
                elif btype == "qr" and (not isinstance(block.get("value"), str) or
                                         len(block["value"]) > 1000 or
                                         block.get("size", 6) not in range(1, 17)):
                    raise ValidationError(_("Bloque QR inválido"))
                elif btype == "barcode" and (
                        not isinstance(block.get("value"), str) or
                        len(block["value"]) > 100 or
                        block.get("symbology") not in
                        ("EAN13", "EAN8", "UPC-A", "UPC-E", "CODE128", "CODE39", "ITF") or
                        block.get("height", 60) not in range(1, 256)):
                    raise ValidationError(_("Bloque de código de barras inválido"))
                elif btype == "image":
                    source = block.get("source")
                    if source not in ("logo", "base64"):
                        raise ValidationError(_("Origen de imagen inválido"))
                    width = block.get("width")
                    if width is not None and width not in range(1, 577):
                        raise ValidationError(_("Ancho de imagen inválido"))
                    if source == "base64":
                        data = block.get("data")
                        if not isinstance(data, str) or not data:
                            raise ValidationError(_("Imagen base64 vacía"))
                        try:
                            raw = base64.b64decode(data, validate=True)
                        except (binascii.Error, ValueError) as exc:
                            raise ValidationError(_("Imagen base64 inválida")) from exc
                        if len(raw) > MAX_IMAGE_BYTES:
                            raise ValidationError(_("Imagen superior a 300 KB"))
        return super().create(vals_list)

    # ------------------------------------------------------------------- envío

    def _payload_document(self) -> dict:
        self.ensure_one()
        return json.loads(self.payload_json)

    def _post_job(self):
        """Despacha desde un cron/acción de administración, nunca desde RPC POS."""
        for job in self:
            server = job.printer_id.server_id
            ok, data = server.lba_post_job(job)
            if ok:
                data = data or {}
                remote_status = data.get("status") or "pending"
                vals = {
                    "external_job_id": data.get("id", job.external_job_id),
                    "server_status": remote_status,
                    "last_error": False,
                }
                if remote_status == "sent":
                    vals.update({"state": "sent", "sent_at":
                                 fields.Datetime.now()})
                elif remote_status in ("failed", "cancelled"):
                    vals.update({"state": remote_status,
                                 "last_error": data.get("last_error") or False})
                else:
                    vals["state"] = "queued"
                job.write(vals)
            else:
                job.attempts += 1
                error = str(data or _("Error al enviar al servidor LBA"))[:500]
                if job.attempts >= job.max_attempts:
                    job.write({"state": "failed", "last_error": error})
                else:
                    delay = BACKOFF_S[min(job.attempts - 1, len(BACKOFF_S) - 1)]
                    job.write({
                        "state": "pending",
                        "last_error": error,
                        "next_attempt": fields.Datetime.now() + timedelta(seconds=delay),
                    })
        return True

    def action_process_now(self):
        self._check_pos_manager()
        # This public button may process only the records selected by the
        # manager. The global queue remains exclusively in the private cron.
        for job in self.filtered(lambda item: item.state == "pending"):
            job._post_job()
        return True

    def _check_pos_manager(self):
        if not self.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("Solo los responsables del TPV pueden operar la cola LBA"))

    def action_cancel(self):
        self._check_pos_manager()
        self.filtered(lambda j: j.state == "pending").write(
            {"state": "cancelled"})
        return True

    def action_retry(self):
        self._check_pos_manager()
        self.filtered(lambda j: j.state == "failed").write({
            "state": "pending", "attempts": 0, "next_attempt":
                fields.Datetime.now(), "last_error": False})
        return True

    # -------------------------------------------------------------------- cron

    @api.model
    def _cron_process_pending(self):
        """Reclama filas con SKIP LOCKED para impedir envíos concurrentes."""
        now = fields.Datetime.now()
        self.env.cr.execute(
            "SELECT id FROM lba_print_job "
            "WHERE state = 'pending' AND next_attempt <= %s "
            "ORDER BY create_date, id LIMIT 50 FOR UPDATE SKIP LOCKED",
            [now],
        )
        jobs = self.browse([row[0] for row in self.env.cr.fetchall()])
        for job in jobs:
            try:
                with self.env.cr.savepoint():
                    job._post_job()
            except Exception as exc:  # nunca romper el cron completo
                _logger.exception("LBA job %s: %s", job.uuid, exc)
                attempts = job.attempts + 1
                vals = {"attempts": attempts,
                        "last_error": f"{type(exc).__name__}: {exc}"[:500]}
                if attempts >= job.max_attempts:
                    vals["state"] = "failed"
                else:
                    vals.update({"state": "pending",
                                 "next_attempt": now + timedelta(
                                     seconds=BACKOFF_S[min(
                                         attempts - 1, len(BACKOFF_S) - 1)])})
                job.write(vals)

    @api.model
    def _cron_update_states(self):
        """Sincroniza estados; ``sent`` no equivale a papel impreso."""
        jobs = self.search([("state", "in", ("queued", "sent")),
                            ("external_job_id", "!=", False)], limit=100)
        for job in jobs:
            server = job.printer_id.server_id
            data = server.lba_get_job(job.external_job_id)
            if not data:
                continue
            srv_status = data.get("status")
            vals = {"server_status": srv_status}
            if srv_status == "failed":
                vals.update({"state": "failed",
                             "last_error": data.get("last_error") or
                             "Servidor LBA informó fallo"})
            elif srv_status == "cancelled":
                vals["state"] = "cancelled"
            elif srv_status == "sent":
                vals.update({"state": "sent", "sent_at": job.sent_at or
                             fields.Datetime.now()})
            elif srv_status in ("pending", "processing"):
                vals["state"] = "queued"
            else:
                continue
            job.write(vals)
