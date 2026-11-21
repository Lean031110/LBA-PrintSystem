# -*- coding: utf-8 -*-
"""Tests del modelo de servidor (con HTTP mockeado)."""
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


def _resp(status=200, payload=None):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload or {}
    m.text = ""
    m.raise_for_status.return_value = None
    return m


class TestLbaServer(TransactionCase):
    def test_connection_ok_and_sync(self):
        server = self.env["lba.print.server"].create({
            "name": "LBA test", "base_url": "http://127.0.0.1",
            "port": 8000, "api_token": "lba_test",
        })
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(200, {"status": "ok", "app": "LBA Print Server",
                                           "version": "0.1.0", "printers": 2})
            server.action_test_connection()
            self.assertEqual(server.state, "online")
            self.assertIn("2 impresoras", server.last_message)

            req.return_value = _resp(200, {"items": [
                {"id": "p-1", "name": "Cocina", "manufacturer": "Rongta",
                 "model": "RP326", "ip": "192.168.1.61", "port": 9100,
                 "paper_width_mm": 80, "columns": 48, "encoding": "CP850",
                 "status": "online", "protocol": "escpos_raw_tcp",
                 "connection_type": "network"},
            ], "count": 1})
            server.action_sync_printers()
            self.assertEqual(len(server.printer_ids), 1)
            printer = server.printer_ids[0]
            self.assertEqual(printer.external_id, "p-1")
            self.assertEqual(printer.paper_width_mm, 80)

    def test_connection_fail(self):
        server = self.env["lba.print.server"].create({
            "name": "LBA down", "base_url": "http://127.0.0.1",
            "port": 8000, "api_token": "lba_test",
        })
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.side_effect = ConnectionError("sin conexión")
            server.action_test_connection()
            self.assertEqual(server.state, "offline")
            self.assertIn("ConnectionError", server.last_message)
