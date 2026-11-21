"""Jobs: idempotencia, contratos de payload, reimpresión, cancelación."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _printer(client, headers, name="ImpJobs"):
    r = client.post("/api/v1/printers", headers=headers,
                    json={"name": name, "ip": "127.0.0.1", "port": 9910,
                          "profile": "simulator"})
    return r.json()["id"]


def _job(printer_id, key=None):
    doc = {"type": "ticket", "blocks": [
        {"type": "text", "value": "COMANDA — Mesa 4", "bold": True},
        {"type": "ruler"},
        {"type": "text", "value": "2 x Pizza Especial"},
        {"type": "qr", "value": "order:00042", "size": 6},
        {"type": "cut"},
    ]}
    body = {"printer_id": printer_id, "origin": "odoo", "document": doc}
    if key:
        body["idempotency_key"] = key
    return body


def test_idempotencia_misma_clave_no_duplica(client: TestClient, auth_headers):
    pid = _printer(client, auth_headers, name="ImpIdem")
    key = "odoo:order-42:delta-abc:printer-1"
    r1 = client.post("/api/v1/jobs", headers=auth_headers,
                     json=_job(pid, key))
    assert r1.status_code == 202
    r2 = client.post("/api/v1/jobs", headers=auth_headers,
                     json=_job(pid, key))
    assert r2.status_code == 409
    assert r2.json()["detail"]["job"]["duplicate"] is True
    assert r2.json()["detail"]["job"]["id"] == r1.json()["id"]
    # en la cola solo hay UN trabajo con esa clave
    lst = client.get("/api/v1/jobs", headers=auth_headers,
                     params={"printer_id": pid}).json()
    assert lst["count"] == 1


def test_payload_invalido_rechazado(client: TestClient, auth_headers):
    pid = _printer(client, auth_headers, name="ImpPayload")
    # bloque desconocido
    r = client.post("/api/v1/jobs", headers=auth_headers,
                    json={"printer_id": pid, "document": {
                        "type": "ticket",
                        "blocks": [{"type": "video", "value": "x"}]}})
    assert r.status_code == 422
    # barcode inválido (EAN13 con letras)
    r = client.post("/api/v1/jobs", headers=auth_headers,
                    json={"printer_id": pid, "document": {
                        "type": "ticket",
                        "blocks": [{"type": "barcode", "value": "ABC",
                                    "symbology": "EAN13"}]}})
    assert r.status_code == 422
    # texto demasiado largo
    r = client.post("/api/v1/jobs", headers=auth_headers,
                    json={"printer_id": pid, "document": {
                        "type": "ticket",
                        "blocks": [{"type": "text", "value": "x" * 5000}]}})
    assert r.status_code == 422
    # imagen base64 inválida
    r = client.post("/api/v1/jobs", headers=auth_headers,
                    json={"printer_id": pid, "document": {
                        "type": "ticket",
                        "blocks": [{"type": "image", "source": "base64",
                                    "data": "###no-base64###"}]}})
    assert r.status_code == 422


def test_printer_inexistente_404(client: TestClient, auth_headers):
    r = client.post("/api/v1/jobs", headers=auth_headers,
                    json=_job("no-existe-000"))
    assert r.status_code == 404


def test_reprint_crea_job_nuevo(client: TestClient, auth_headers):
    pid = _printer(client, auth_headers, name="ImpReprint")
    r = client.post("/api/v1/jobs", headers=auth_headers, json=_job(pid))
    jid = r.json()["id"]
    r2 = client.post(f"/api/v1/jobs/{jid}/reprint", headers=auth_headers)
    assert r2.status_code == 202
    assert r2.json()["id"] != jid
    assert r2.json()["origin"] == "reprint"
    lst = client.get("/api/v1/jobs", headers=auth_headers,
                     params={"printer_id": pid}).json()
    assert lst["count"] == 2


def test_cancel_pendiente(client: TestClient, auth_headers):
    pid = _printer(client, auth_headers, name="ImpCancel")
    jid = client.post("/api/v1/jobs", headers=auth_headers,
                      json=_job(pid)).json()["id"]
    r = client.post(f"/api/v1/jobs/{jid}/cancel", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    r2 = client.post(f"/api/v1/jobs/{jid}/cancel", headers=auth_headers)
    assert r2.status_code == 409      # ya no es pendiente


def test_eventos_registrados(client: TestClient, auth_headers):
    pid = _printer(client, auth_headers, name="ImpEvents")
    jid = client.post("/api/v1/jobs", headers=auth_headers,
                      json=_job(pid)).json()["id"]
    detail = client.get(f"/api/v1/jobs/{jid}", headers=auth_headers).json()
    assert detail["status"] == "pending"
    assert any(e["to"] == "pending" for e in detail["events"])
