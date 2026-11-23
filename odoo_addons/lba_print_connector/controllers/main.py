# -*- coding: utf-8 -*-
"""Controlador propio llamado desde el TPV con rpc() (patrón del core hw_printer).

Ruta type='jsonrpc' (en 19 'json' está deprecado), auth='user' (cookie de
sesión del TPV) y CSRF deshabilitado por defecto para jsonrpc, igual que
/web/dataset/call_kw.
"""
from __future__ import annotations

import logging
import json
import re

from psycopg2 import IntegrityError

from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_BLOCKS = 200
MAX_KEY_LENGTH = 200
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_:\-.]+$")
ALLOWED_KINDS = {"receipt", "kitchen", "delta", "reprint"}


class LbaPrintController(http.Controller):

    @http.route("/lba_print/jobs", type="jsonrpc", auth="user",
                methods=["POST"], csrf=False, save_session=False)
    def lba_print_jobs(self, printer_id=None, kind="kitchen", document=None,
                       order_ref=None, order_uuid=None, department_id=None,
                       idempotency_key=None, **kwargs):
        """Encola un trabajo LBA desde el frontend del TPV.

        params:
          printer_id     → int, id de lba.print.printer
          kind           → receipt | kitchen | delta | reprint
          document       → {"type":"ticket","blocks":[…]} (payload estructurado)
          order_ref/uuid, department_id, idempotency_key
        returns: {"state": …, "job": {uuid,…}, "error": …}
        """
        Job = request.env["lba.print.job"].sudo()
        Printer = request.env["lba.print.printer"].sudo()
        try:
            printer = Printer.browse(int(printer_id or 0)).exists()
        except (TypeError, ValueError):
            printer = Printer.browse()
        if not printer or not printer.active or not printer.server_id or \
                printer.server_id.company_id not in request.env.user.company_ids:
            return {"state": "error",
                    "error": _("Impresora LBA no encontrada/inactiva")}
        if kind not in ALLOWED_KINDS:
            return {"state": "error", "error": _("Tipo de trabajo inválido")}
        if not isinstance(document, dict) or document.get("type") != "ticket" or \
                not isinstance(document.get("blocks"), list) or \
                not (1 <= len(document["blocks"]) <= MAX_BLOCKS):
            return {"state": "error", "error": _("Payload inválido")}
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or \
                len(idempotency_key) > MAX_KEY_LENGTH or \
                not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
            return {"state": "error",
                    "error": _("Falta una clave idempotente de operación válida")}
        if not order_uuid:
            return {"state": "error", "error": _("Falta el UUID del pedido")}
        try:
            department = request.env["lba.print.department"].sudo().browse(
                int(department_id or 0)).exists() if department_id else False
        except (TypeError, ValueError):
            return {"state": "error", "error": _("Departamento inválido")}
        if department and printer not in department.printer_ids:
            return {"state": "error",
                    "error": _("La impresora no pertenece al departamento")}

        key = idempotency_key.strip()
        existing = Job.search([("idempotency_key", "=", key)], limit=1)
        if existing:
            same_operation = (
                existing.printer_id.id == printer.id and
                existing.kind == kind and
                existing.order_uuid == (order_uuid or "") and
                existing.order_ref == (order_ref or "") and
                existing.department_id.id == (department.id if department else False) and
                json.loads(existing.payload_json) == document
            )
            if not same_operation:
                return {"state": "error",
                        "error": _("La clave idempotente ya se usó para otro documento")}
            return {"state": existing.state, "job": {"uuid": existing.uuid},
                    "external_job_id": existing.external_job_id or False}

        values = {
            "printer_id": printer.id,
            "kind": kind,
            "payload_json": json.dumps(document, ensure_ascii=False,
                                        sort_keys=True, separators=(",", ":")),
            "order_ref": order_ref or "",
            "order_uuid": order_uuid or "",
            "department_id": department.id if department else False,
            "idempotency_key": key,
        }
        try:
            with request.env.cr.savepoint():
                job = Job.create(values)
        except IntegrityError:
            # Dos retries concurrentes con la misma clave deben converger.
            job = Job.search([("idempotency_key", "=", key)], limit=1)
            if not job:
                raise
            same_operation = (
                job.printer_id.id == printer.id and job.kind == kind and
                job.order_uuid == (order_uuid or "") and
                job.order_ref == (order_ref or "") and
                job.department_id.id == (department.id if department else False) and
                json.loads(job.payload_json) == document
            )
            if not same_operation:
                return {"state": "error",
                        "error": _("La clave idempotente ya se usó para otro documento")}
        except ValidationError as exc:
            return {"state": "error", "error": str(exc)}
        return {
            "state": "pending" if job.state == "pending" else job.state,
            "job": {"uuid": job.uuid},
            "external_job_id": job.external_job_id or False,
            "error": False,
        }
