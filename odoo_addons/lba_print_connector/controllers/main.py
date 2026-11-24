# -*- coding: utf-8 -*-
"""Controlador propio llamado desde el TPV con rpc() autenticado."""
from __future__ import annotations

import json
import logging
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


def _int_id(value):
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _authorized_pos_config(env, config_id, session_id):
    """Return a POS config only for its authenticated, currently open session."""
    if not env.user.has_group("point_of_sale.group_pos_user"):
        return env["pos.config"].browse(), "pos_user_required"
    config_id = _int_id(config_id)
    session_id = _int_id(session_id)
    if not config_id or not session_id:
        return env["pos.config"].browse(), "pos_session_required"

    config = env["pos.config"].search([
        ("id", "=", config_id), ("lba_active", "=", True),
    ], limit=1)
    session = env["pos.session"].search([
        ("id", "=", session_id),
        ("config_id", "=", config_id),
        ("user_id", "=", env.uid),
        ("state", "=", "opened"),
    ], limit=1)
    if not config or not session:
        return env["pos.config"].browse(), "pos_session_required"
    return config, False


class LbaPrintController(http.Controller):

    @http.route("/lba_print/jobs", type="jsonrpc", auth="user",
                methods=["POST"], csrf=False, save_session=False)
    def lba_print_jobs(self, config_id=None, session_id=None, printer_id=None,
                       kind="kitchen", document=None, order_ref=None,
                       order_uuid=None, department_id=None,
                       idempotency_key=None, **kwargs):
        """Encola un trabajo desde una sesión POS abierta y autorizada.

        El request necesita el ID de configuración y sesión, que se validan
        contra el usuario autenticado; ningún dato recibido permite elevar a
        sudo ni seleccionar una impresora ajena a esa configuración.
        """
        env = request.env
        config, auth_error = _authorized_pos_config(env, config_id, session_id)
        if auth_error:
            return {"state": "error", "code": auth_error,
                    "error": _("Se requiere una sesión TPV abierta y autorizada")}
        if kind not in ALLOWED_KINDS:
            return {"state": "error", "code": "invalid_kind",
                    "error": _("Tipo de trabajo inválido")}
        if not isinstance(document, dict) or document.get("type") != "ticket" or \
                not isinstance(document.get("blocks"), list) or \
                not (1 <= len(document["blocks"]) <= MAX_BLOCKS):
            return {"state": "error", "code": "invalid_document",
                    "error": _("Payload inválido")}
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or \
                len(idempotency_key) > MAX_KEY_LENGTH or \
                not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
            return {"state": "error", "code": "invalid_idempotency_key",
                    "error": _("Falta una clave idempotente de operación válida")}
        if not order_uuid:
            return {"state": "error", "code": "missing_order_uuid",
                    "error": _("Falta el UUID del pedido")}

        printer_id = _int_id(printer_id)
        domain = [
            ("id", "=", printer_id), ("active", "=", True),
            ("server_id.active", "=", True),
            ("server_id.company_id", "=", config.company_id.id),
        ]
        if config.lba_server_id:
            domain.append(("server_id", "=", config.lba_server_id.id))
        printer = env["lba.print.printer"].search(domain, limit=1)
        if not printer:
            return {"state": "error", "code": "printer_unavailable",
                    "error": _("Impresora LBA no encontrada/inactiva")}

        department = env["lba.print.department"].browse()
        if kind == "receipt":
            if config.lba_receipt_printer_id != printer:
                return {"state": "error", "code": "printer_not_allowed",
                        "error": _("La impresora no está configurada para recibos")}
        else:
            dep_id = _int_id(department_id)
            if not dep_id:
                return {"state": "error", "code": "department_required",
                        "error": _("Se requiere el departamento del TPV")}
            department = env["lba.print.department"].search([
                ("id", "=", dep_id), ("active", "=", True),
                ("printer_ids", "in", printer.id),
            ], limit=1)
            if not department:
                return {"state": "error", "code": "printer_not_allowed",
                        "error": _("La impresora no pertenece al departamento activo")}

        Job = env["lba.print.job"]
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
                return {"state": "error", "code": "idempotency_conflict",
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
            with env.cr.savepoint():
                # Escalation occurs only after the authenticated open POS
                # session, company, printer and department have been checked.
                job = Job.sudo().create(values)
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
                return {"state": "error", "code": "idempotency_conflict",
                        "error": _("La clave idempotente ya se usó para otro documento")}
        except ValidationError as exc:
            return {"state": "error", "code": "invalid_document", "error": str(exc)}
        return {
            "state": "pending" if job.state == "pending" else job.state,
            "job": {"uuid": job.uuid},
            "external_job_id": job.external_job_id or False,
            "error": False,
        }
