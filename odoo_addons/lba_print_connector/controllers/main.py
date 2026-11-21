# -*- coding: utf-8 -*-
"""Controlador propio llamado desde el TPV con rpc() (patrón del core hw_printer).

Ruta type='jsonrpc' (en 19 'json' está deprecado), auth='user' (cookie de
sesión del TPV) y CSRF deshabilitado por defecto para jsonrpc, igual que
/web/dataset/call_kw.
"""
from __future__ import annotations

import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_BLOCKS = 200


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

        printer = Printer.browse(int(printer_id or 0)) if printer_id else None
        if not printer or not printer.active or not printer.server_id:
            return {"state": "error",
                    "error": _("Impresora LBA no encontrada/inactiva")}

        if not isinstance(document, dict) or \
                document.get("type") != "ticket" or \
                not isinstance(document.get("blocks"), list) or \
                not (1 <= len(document["blocks"]) <= MAX_BLOCKS):
            return {"state": "error", "error": _("Payload inválido")}

        key = idempotency_key or f"pos:{order_uuid}:{kind}:{printer.id}"

        # Idempotencia en Odoo: si ya existe, no duplicar
        existing = Job.search([("idempotency_key", "=", key)], limit=1)
        if existing:
            if existing.state == "pending":
                # intento inmediato con timeout corto (no bloquea el TPV)
                try:
                    existing._post_job()
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("LBA reintentando %s: %s", key, exc)
            return {"state": existing.state, "job": {"uuid": existing.uuid},
                    "external_job_id": existing.external_job_id or False}

        job = Job.create({
            "printer_id": printer.id,
            "kind": kind,
            "payload_json": http.json.dumps(document),
            "order_ref": order_ref or "",
            "order_uuid": order_uuid or "",
            "department_id": int(department_id) if department_id else False,
            "idempotency_key": key,
        })
        # Envío inmediato con timeout corto (≈3 s máx.): el TPV no se congela.
        # Si falla, queda 'pending' en la cola Odoo y el cron reintenta.
        try:
            job._post_job()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("LBA job %s falló (se reintenta por cron): %s",
                            job.uuid, exc)
            job.write({"state": "pending",
                       "last_error": f"{type(exc).__name__}: {exc}"[:250]})
        return {
            "state": job.state,
            "job": {"uuid": job.uuid},
            "external_job_id": job.external_job_id or False,
            "error": job.last_error if job.state != "sent" else False,
        }
