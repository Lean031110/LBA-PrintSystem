# -*- coding: utf-8 -*-
"""Tests de la cola de salida lba.print.job (HTTP mockeado)."""
import json
from unittest.mock import MagicMock, patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


def _resp(status=200, payload=None):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload or {}
    m.text = ""
    m.raise_for_status.return_value = None
    return m


class TestLbaJob(TransactionCase):
    def _job(self, kind="kitchen", key="odoo:t:1", blocks=None):
        server = self.env["lba.print.server"].create({
            "name": "S", "base_url": "http://127.0.0.1", "port": 8000,
            "api_token": "tok"})
        printer = self.env["lba.print.printer"].create({
            "server_id": server.id, "external_id": "p-1", "name": "Cocina"})
        payload = {"type": "ticket",
                   "blocks": blocks or [{"type": "text", "value": "ñá"}]}
        return self.env["lba.print.job"].create({
            "printer_id": printer.id, "kind": kind,
            "payload_json": json.dumps(payload),
            "order_ref": "Order 1", "order_uuid": "u-1",
            "idempotency_key": key,
        })

    def test_post_sent(self):
        job = self._job()
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(202, {"id": "ext-9", "status": "pending"})
            job._post_job()
            self.assertEqual(job.state, "sent")
            self.assertEqual(job.external_job_id, "ext-9")
            # el POST lleva el payload estructurado (no binarios ESC/POS)
            sent = req.call_args[1]["json"]
            self.assertEqual(sent["document"]["blocks"][0]["value"], "ñá")
            self.assertEqual(sent["idempotency_key"], "odoo:t:1")

    def test_post_fail_reintento_pendiente(self):
        job = self._job(key="odoo:t:2")
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(500, {})
            job._post_job()
            self.assertEqual(job.state, "pending")
            self.assertEqual(job.attempts, 1)
            self.assertTrue(job.next_attempt)

    def test_post_fail_agota_intentos_y_retry(self):
        job = self._job(key="odoo:t:3", kind="receipt")
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(500, {})
            for _ in range(5):
                job._post_job()
            self.assertEqual(job.state, "failed")
            self.assertEqual(job.attempts, 5)
            job.action_retry()
            self.assertEqual(job.state, "pending")
            self.assertEqual(job.attempts, 0)

    def test_idempotencia_409_no_duplica(self):
        job = self._job(key="odoo:t:4")
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(409, {"detail": {"job": {"id": "ext-1"}}})
            job._post_job()
            self.assertEqual(job.state, "sent")
            self.assertEqual(job.external_job_id, "ext-1")

    def test_clave_idempotente_unica(self):
        self._job(key="odoo:t:5")
        with self.assertRaises(ValidationError):
            self._job(key="odoo:t:5")

    def test_payload_invalido_rechazado(self):
        with self.assertRaises(ValidationError):
            self._job(key="odoo:t:6", blocks=[])

    def test_cron_procesa_pendientes(self):
        job = self._job(key="odoo:t:7")
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(202, {"id": "ext-c"})
            self.env["lba.print.job"]._cron_process_pending()
            self.assertEqual(job.state, "sent")
