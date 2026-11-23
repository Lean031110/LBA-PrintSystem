# -*- coding: utf-8 -*-
"""Configuración del LBA Print Server (URL, puerto, token, estado)."""
from __future__ import annotations

import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TIMEOUT_CONNECT_S = 2.5
TIMEOUT_READ_S = 4.0


class LbaPrintServer(models.Model):
    _name = "lba.print.server"
    _description = "LBA Print Server (configuración)"
    _order = "sequence, id"

    name = fields.Char(required=True, default="LBA Print Server")
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True)
    base_url = fields.Char(
        "URL", required=True, help="Ej.: http://192.168.1.50 (sin puerto ni /api)")
    port = fields.Integer(default=8000, required=True)
    api_token = fields.Char(
        groups="base.group_system", copy=False,
        help="Token generado en el panel de LBA → Seguridad → Crear token. "
             "Solo visible para administradores.")
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [("draft", "Sin verificar"), ("online", "Conectado"),
         ("offline", "Sin conexión")],
        default="draft", copy=False)
    last_check = fields.Datetime(readonly=True, copy=False)
    last_message = fields.Char(readonly=True, copy=False)
    printer_ids = fields.One2many("lba.print.printer", "server_id",
                                  string="Impresoras sincronizadas")
    printer_count = fields.Integer(compute="_compute_printer_count")

    _name_company_uniq = models.Constraint(
        "unique(name, company_id)",
        "Ya existe un servidor LBA con ese nombre",
    )

    # ------------------------------------------------------------------ helpers

    def _api_url(self, path: str) -> str:
        self.ensure_one()
        base = (self.base_url or "").rstrip("/")
        if not base:
            raise UserError(_("Configura la URL del LBA Print Server"))
        return f"{base}:{int(self.port or 8000)}/api/v1{path}"

    def _headers(self) -> dict:
        self.ensure_one()
        if not self.api_token:
            raise UserError(_("Configura el token del LBA Print Server"))
        return {"Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"}

    def _request(self, method: str, path: str, **kwargs):
        """HTTP a LBA con timeouts cortos (nunca bloquear al TPV por mucho)."""
        self.ensure_one()
        kwargs.setdefault("timeout", (TIMEOUT_CONNECT_S, TIMEOUT_READ_S))
        return requests.request(method, self._api_url(path),
                                 headers=self._headers(), **kwargs)

    @api.depends("printer_ids")
    def _compute_printer_count(self):
        for server in self:
            server.printer_count = len(server.printer_ids)

    # ---------------------------------------------------------------- acciones

    def action_test_connection(self):
        for server in self:
            try:
                resp = server._request("GET", "/health")
                payload = resp.json()
                server.write({
                    "state": "online" if resp.status_code == 200 else "offline",
                    "last_check": fields.Datetime.now(),
                    "last_message": _("OK · %s v%s · %s impresoras") % (
                        payload.get("app"), payload.get("version"),
                        payload.get("printers")),
                })
            except Exception as exc:  # requests/JSON/timeout
                server.write({
                    "state": "offline",
                    "last_check": fields.Datetime.now(),
                    "last_message": f"{type(exc).__name__}: {exc}"[:250],
                })
        return self._notify(_("Conexión verificada: %s") %
                            ", ".join(f"{s.name}: {s.state}" for s in self))

    def action_sync_printers(self):
        """GET /printers → réplica local lba.print.printer."""
        for server in self:
            try:
                resp = server._request("GET", "/printers")
                resp.raise_for_status()
                items = resp.json().get("items", [])
            except Exception as exc:
                server.write({"state": "offline",
                              "last_check": fields.Datetime.now(),
                              "last_message": f"{type(exc).__name__}: {exc}"[:250]})
                return self._notify(
                    _("No se pudo sincronizar: %s") % server.last_message,
                    kind="danger")
            Printer = self.env["lba.print.printer"]
            existing = {p.external_id: p for p in server.printer_ids}
            created = 0
            for item in items:
                ext = item.get("id")
                vals = {
                    "name": item.get("name") or ext,
                    "manufacturer": item.get("manufacturer", ""),
                    "model": item.get("model", ""),
                    "ip": item.get("ip", ""),
                    "port": int(item.get("port") or 9100),
                    "connection_type": item.get("connection_type", "network"),
                    "protocol": item.get("protocol", "escpos_raw_tcp"),
                    "paper_width_mm": int(item.get("paper_width_mm") or 80),
                    "columns": int(item.get("columns") or 48),
                    "encoding": item.get("encoding", ""),
                    "status": item.get("status", "unknown"),
                }
                if ext in existing:
                    existing[ext].write(vals)
                else:
                    Printer.create(dict(vals, server_id=server.id,
                                        external_id=ext))
                    created += 1
            server.write({"state": "online",
                          "last_check": fields.Datetime.now(),
                          "last_message": _("Sincronizadas %d impresoras") %
                          len(items)})
            return self._notify(
                _("Sincronización: %d impresoras (%d nuevas)") %
                (len(items), created))
        return True

    # ------------------------------------------------------------------- cola

    def lba_post_job(self, job):
        """POST /jobs para un lba.print.job. Devuelve (ok, respuesta)."""
        self.ensure_one()
        server = job.printer_id.server_id
        if not server or not server.active:
            return False, "servidor LBA no configurado/inactivo"
        document = job._payload_document()
        body = {
            "printer_id": job.printer_id.external_id,
            "idempotency_key": job.idempotency_key,
            "origin": "odoo",
            "metadata": {
                "kind": job.kind,
                "order_ref": job.order_ref or "",
                "order_uuid": job.order_uuid or "",
                "department": job.department_id.name or "",
                "reprint": job.kind == "reprint",
            },
            "document": document,
        }
        try:
            if job.external_job_id and job.server_status == "failed":
                resp = server._request(
                    "POST", f"/jobs/{job.external_job_id}/retry")
                if resp.status_code == 200:
                    return True, resp.json()
                if resp.status_code == 409:
                    current = server.lba_get_job(job.external_job_id) or {}
                    if current.get("status") in ("pending", "processing", "sent"):
                        return True, current
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
            resp = server._request("POST", "/jobs", json=body)
            if resp.status_code in (200, 202):
                data = resp.json()
                return True, data
            if resp.status_code == 409:
                # idempotencia: el servidor ya lo tiene (por un reintento previo)
                data = resp.json().get("detail", {}).get("job", {})
                if data.get("status") == "failed":
                    return False, "El trabajo remoto falló; reintentar su ID existente"
                return True, data
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"[:250]

    def lba_get_job(self, external_job_id: str):
        self.ensure_one()
        try:
            resp = self._request("GET", f"/jobs/{external_job_id}")
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def _notify(self, message: str, kind: str = "success"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": kind, "sticky": False},
        }
