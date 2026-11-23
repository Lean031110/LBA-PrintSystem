# -*- coding: utf-8 -*-
"""Cola de salida persistente en Odoo (cuando LBA no responde)."""
from __future__ import annotations

import json
import logging
import uuid as uuidlib
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

MAX_BLOCKS = 200
MAX_TEXT_CHARS = 4000

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
        [("pending", "Pendiente"), ("sent", "Enviado"),
         ("failed", "Fallido"), ("cancelled", "Cancelado")],
        default="pending", required=True, copy=False)
    attempts = fields.Integer(default=0)
    max_attempts = fields.Integer(default=5)
    next_attempt = fields.Datetime(default=fields.Datetime.now)
    last_error = fields.Text(readonly=True, copy=False)
    external_job_id = fields.Char(readonly=True, copy=False)
    sent_at = fields.Datetime(readonly=True, copy=False)
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
        for vals in vals_list:
            if not vals.get("uuid"):
                vals["uuid"] = str(uuidlib.uuid4())
            if not vals.get("idempotency_key"):
                vals["idempotency_key"] = vals["uuid"]
            # saneo mínimo del documento
            doc = json.loads(vals.get("payload_json") or '{"blocks": []}')
            blocks = doc.get("blocks", [])
            if not blocks or len(blocks) > MAX_BLOCKS:
                raise ValidationError(
                    _("El documento necesita entre 1 y %d bloques") % MAX_BLOCKS)
            for b in blocks:
                if b.get("type") == "text" and len(b.get("value", "")) > MAX_TEXT_CHARS:
                    raise ValidationError(
                        _("Bloque de texto demasiado largo (máx. %d)") % MAX_TEXT_CHARS)
        return super().create(vals_list)

    # ------------------------------------------------------------------- envío

    def _payload_document(self) -> dict:
        self.ensure_one()
        return json.loads(self.payload_json)

    def _post_job(self):
        """Intento único de envío al LBA Server (timeout corto)."""
        for job in self:
            server = job.printer_id.server_id
            ok, data = server.lba_post_job(job)
            if ok:
                job.write({
                    "state": "sent",
                    "sent_at": fields.Datetime.now(),
                    "external_job_id": (data or {}).get("id",
                                                        job.external_job_id),
                    "last_error": "",
                })
            else:
                job.attempts += 1
                if job.attempts >= job.max_attempts:
                    job.write({"state": "failed", "last_error": data})
                else:
                    job.write({
                        "state": "pending",
                        "last_error": data,
                        "next_attempt": fields.Datetime.now() + timedelta(
                            seconds=BACKOFF_S[min(job.attempts - 1,
                                                  len(BACKOFF_S) - 1)]),
                    })
        return True

    def action_process_now(self):
        pending = self.filtered(lambda j: j.state == "pending")
        pending._post_job()
        return True

    def action_cancel(self):
        self.filtered(lambda j: j.state == "pending").write(
            {"state": "cancelled"})
        return True

    def action_retry(self):
        self.filtered(lambda j: j.state == "failed").write({
            "state": "pending", "attempts": 0, "next_attempt":
                fields.Datetime.now()})
        return True

    # -------------------------------------------------------------------- cron

    @api.model
    def _cron_process_pending(self):
        """Cada minuto: envía los pendientes cuya hora llegó."""
        jobs = self.search(
            [("state", "=", "pending"),
             ("next_attempt", "<=", fields.Datetime.now())], limit=50)
        for job in jobs:
            try:
                with self.env.cr.savepoint():
                    job._post_job()
            except Exception as exc:  # nunca romper el cron completo
                _logger.exception("LBA job %s: %s", job.uuid, exc)
                job.write({"last_error": f"{type(exc).__name__}: {exc}"[:250],
                           "state": "failed" if job.attempts >= job.max_attempts
                           else "pending"})
            # commit por trabajo: un error no arrastra los anteriores
            self.env.cr.commit()

    @api.model
    def _cron_update_states(self):
        """Cada 5 min: refresca el estado servidor de los 'sent'."""
        jobs = self.search([("state", "=", "sent"),
                            ("external_job_id", "!=", False)], limit=100)
        for job in jobs:
            server = job.printer_id.server_id
            data = server.lba_get_job(job.external_job_id)
            if not data:
                continue
            srv_status = data.get("status")
            if srv_status == "failed":
                job.write({"state": "failed",
                           "last_error": data.get("last_error") or "servidor LBA"})
            elif srv_status == "sent":
                job.write({"sent_at": job.sent_at or fields.Datetime.now()})
