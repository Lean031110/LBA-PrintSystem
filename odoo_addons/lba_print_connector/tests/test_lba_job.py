# -*- coding: utf-8 -*-
"""Tests de la cola de salida lba.print.job (HTTP mockeado)."""
import json
import uuid
from unittest.mock import MagicMock, patch

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, ValidationError
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
            "name": f"S-{uuid.uuid4()}",
            "base_url": "http://127.0.0.1", "port": 8000,
            "api_token": "tok"})
        printer = self.env["lba.print.printer"].create({
            "server_id": server.id, "external_id": "p-1", "name": "Cocina"})
        payload = {"type": "ticket",
                   "blocks": ([{"type": "text", "value": "ñá"}]
                              if blocks is None else blocks)}
        return self.env["lba.print.job"].create({
            "printer_id": printer.id, "kind": kind,
            "payload_json": json.dumps(payload),
            "order_ref": "Order 1", "order_uuid": "u-1",
            "idempotency_key": key,
        })

    def test_post_accepted_is_queued_not_physically_sent(self):
        job = self._job()
        self.assertEqual(job.company_id, job.printer_id.server_id.company_id)
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(202, {"id": "ext-9", "status": "pending"})
            job._post_job()
            self.assertEqual(job.state, "queued")
            self.assertEqual(job.server_status, "pending")
            self.assertFalse(job.sent_at)
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
            with patch.object(type(job), "_check_pos_manager"):
                job.action_retry()
            self.assertEqual(job.state, "pending")
            self.assertEqual(job.attempts, 0)

    def test_idempotencia_409_no_duplica(self):
        job = self._job(key="odoo:t:4")
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(409, {"detail": {"job": {
                "id": "ext-1", "status": "pending"}}})
            job._post_job()
            self.assertEqual(job.state, "queued")
            self.assertEqual(job.external_job_id, "ext-1")

    def test_409_sin_job_identificable_no_se_acepta(self):
        job = self._job(key="odoo:t:409-text")
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(409, {"detail": "conflicto sin job"})
            job._post_job()
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.attempts, 1)
        self.assertIn("409 sin trabajo remoto identificable", job.last_error)

    def test_409_con_id_sin_estado_no_se_acepta(self):
        job = self._job(key="odoo:t:409-no-status")
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(409, {"detail": {"job": {
                "id": "ext-no-status"}}})
            job._post_job()
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.attempts, 1)
        self.assertFalse(job.external_job_id)
        self.assertIn("409 sin trabajo remoto identificable", job.last_error)

    def test_idempotencia_409_fallido_conserva_id_para_retry(self):
        job = self._job(key="odoo:t:failed-409")
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(409, {"detail": {"job": {
                "id": "ext-failed-409", "status": "failed",
                "last_error": "paper out",
            }}})
            job._post_job()
            self.assertEqual(job.state, "failed")
            self.assertEqual(job.external_job_id, "ext-failed-409")
            self.assertEqual(job.server_status, "failed")
            self.assertEqual(job.last_error, "paper out")

            req.return_value = _resp(200, {
                "id": "ext-failed-409", "status": "pending"})
            with patch.object(type(job), "_check_pos_manager"):
                job.action_retry()
            job._post_job()
            self.assertEqual(job.state, "queued")
            self.assertEqual(req.call_args.args[1].rsplit("/", 1)[-1], "retry")

    def test_retry_existing_remote_job_uses_retry_endpoint(self):
        job = self._job(key="odoo:t:retry")
        job.write({"state": "failed", "server_status": "failed",
                   "external_job_id": "ext-failed"})
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(200, {"id": "ext-failed", "status": "pending"})
            with patch.object(type(job), "_check_pos_manager"):
                job.action_retry()
            job._post_job()
            self.assertEqual(job.state, "queued")
            self.assertEqual(req.call_args.args[0], "POST")
            self.assertTrue(req.call_args.args[1].endswith("/jobs/ext-failed/retry"))

    def test_clave_idempotente_unica(self):
        self._job(key="odoo:t:5")
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self._job(key="odoo:t:5")

    def test_clave_fuera_del_alfabeto_del_servidor_rechazada(self):
        with self.assertRaises(ValidationError):
            self._job(key="odoo:t:con espacio")

    def test_imagen_base64_invalida_rechazada(self):
        with self.assertRaises(ValidationError):
            self._job(key="odoo:t:bad-image", blocks=[{
                "type": "image", "source": "base64", "data": "not base64!",
            }])

    def test_payload_invalido_rechazado(self):
        with self.assertRaises(ValidationError):
            self._job(key="odoo:t:6", blocks=[])

    def test_documento_no_objeto_rechazado(self):
        server = self.env["lba.print.server"].create({
            "name": "S-invalid", "base_url": "http://127.0.0.1", "port": 8000,
            "api_token": "tok"})
        printer = self.env["lba.print.printer"].create({
            "server_id": server.id, "external_id": "p-invalid", "name": "Cocina"})
        with self.assertRaises(ValidationError):
            self.env["lba.print.job"].create({
                "printer_id": printer.id, "kind": "kitchen",
                "payload_json": json.dumps(["not", "a", "ticket"]),
                "idempotency_key": "odoo:invalid:doc",
            })

    def test_pos_user_y_manager_no_pueden_crear_job_directamente_por_orm_rpc(self):
        reference = self._job(key="odoo:direct:create:reference")
        groups_base = [self.env.ref("base.group_user").id]
        pos_groups = [
            ("user", self.env.ref("point_of_sale.group_pos_user").id),
            ("manager", self.env.ref("point_of_sale.group_pos_manager").id),
        ]
        direct_values = {
            "printer_id": reference.printer_id.id,
            "kind": "kitchen",
            "payload_json": reference.payload_json,
        }
        for label, group_id in pos_groups:
            pos_user = self.env["res.users"].create({
                "name": f"LBA POS {label} Direct Create Test",
                "login": f"lba-pos-{label}-{uuid.uuid4()}",
                "groups_id": [(6, 0, groups_base + [group_id])],
            })
            values = dict(direct_values,
                          idempotency_key=f"odoo:direct:{label}:{uuid.uuid4()}")
            with self.subTest(group=label), self.assertRaises(AccessError):
                self.env["lba.print.job"].with_user(pos_user).create(values)

    def test_cron_procesa_pendientes(self):
        job = self._job(key="odoo:t:7")
        with patch("odoo.addons.lba_print_connector.models.lba_server.requests.request") as req:
            req.return_value = _resp(202, {"id": "ext-c"})
            self.env["lba.print.job"]._cron_process_pending()
            self.assertEqual(job.state, "queued")

    def test_action_process_now_solo_procesa_registros_seleccionados(self):
        selected = self._job(key="odoo:manual:selected")
        unrelated = self._job(key="odoo:manual:unrelated")
        with patch.object(type(selected), "_check_pos_manager"), \
                patch.object(type(selected), "_post_job") as post_job:
            selected.action_process_now()
            post_job.assert_called_once_with(selected)
        self.assertEqual(unrelated.state, "pending")

    def test_action_process_now_requiere_grupo_manager(self):
        job = self._job(key="odoo:manual:forbidden")
        with patch.object(type(job.env.user), "has_group", return_value=False):
            with self.assertRaises(AccessError):
                job.action_process_now()
