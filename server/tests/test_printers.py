"""CRUD de impresoras + validación anti-SSRF + discovery."""
from __future__ import annotations

from fastapi.testclient import TestClient

BASE = {"name": "Cocina", "ip": "127.0.0.1", "port": 9910,
        "manufacturer": "Rongta", "model": "RP326",
        "paper_width_mm": 80, "encoding": "CP850", "profile": "simulator"}


def _create(client, headers, **over):
    body = {**BASE, **over}
    return client.post("/api/v1/printers", json=body, headers=headers)


def test_crear_y_listar(client: TestClient, auth_headers):
    r = _create(client, auth_headers)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["ip"] == "127.0.0.1"
    assert data["columns"] == 48          # 80mm → 48 columnas
    assert data["protocol"] == "escpos_raw_tcp"
    lst = client.get("/api/v1/printers", headers=auth_headers).json()
    assert any(p["id"] == data["id"] for p in lst["items"])


def test_papel_58_32_columnas(client: TestClient, auth_headers):
    r = _create(client, auth_headers, name="Bar 58", paper_width_mm=58)
    assert r.status_code == 201
    assert r.json()["columns"] == 32


def test_update_printer(client: TestClient, auth_headers):
    pid = _create(client, auth_headers, name="Update me").json()["id"]
    r = client.put(f"/api/v1/printers/{pid}", json={"name": "Renombrada",
                                                   "encoding": "CP437"},
                   headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["name"] == "Renombrada"
    assert r.json()["encoding"] == "CP437"


def test_delete_printer_con_historial(client: TestClient, auth_headers):
    pid = _create(client, auth_headers, name="Bórrame").json()["id"]
    r = client.delete(f"/api/v1/printers/{pid}", headers=auth_headers)
    assert r.status_code == 200
    r = client.get(f"/api/v1/printers/{pid}", headers=auth_headers)
    assert r.status_code == 404


def test_ssrf_ip_publica_rechazada(client: TestClient, auth_headers):
    r = _create(client, auth_headers, ip="8.8.8.8")
    assert r.status_code == 400
    assert "SSRF" in r.json()["detail"] or "pública" in r.json()["detail"]


def test_ssrf_metadata_aws_bloqueada(client: TestClient, auth_headers):
    r = _create(client, auth_headers, ip="169.254.169.254")
    assert r.status_code == 400


def test_ssrf_cgnat_bloqueado(client: TestClient, auth_headers):
    r = _create(client, auth_headers, ip="100.64.1.10")
    assert r.status_code == 400


def test_ip_invalida_400(client: TestClient, auth_headers):
    assert _create(client, auth_headers, ip="no-es-una-ip").status_code == 400


def test_discovery_encuentra_simulador(client: TestClient, auth_headers,
                                       simulator, db):
    from app.models import models
    models.set_setting(db, "discovery_ranges", ["127.0.0.0/29"])
    db.commit()
    r = client.post("/api/v1/printers/discover",
                    json={"cidr": "127.0.0.0/29", "ports": [simulator]},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    found = r.json()["found"]
    assert any(f["ip"] == "127.0.0.1" and f["port"] == simulator for f in found)


def test_discovery_range_fuera_de_config_no_escanea(client: TestClient,
                                                     auth_headers, db,
                                                     monkeypatch):
    from app.models import models
    from app.services import discovery
    models.set_setting(db, "discovery_ranges", ["192.168.20.0/24"])
    db.commit()
    called = False

    async def no_scan(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("no debe iniciar el escaneo")

    monkeypatch.setattr(discovery, "scan", no_scan)
    response = client.post("/api/v1/printers/discover", headers=auth_headers,
                           json={"cidr": "192.168.21.0/24"})
    assert response.status_code == 400
    assert "discovery_ranges" in response.json()["detail"]
    assert called is False


def test_discovery_rango_publico_rechazado(client: TestClient, auth_headers):
    r = client.post("/api/v1/printers/discover", json={"cidr": "8.8.8.0/24"},
                    headers=auth_headers)
    assert r.status_code == 400


def test_discovery_rango_enorme_rechazado(client: TestClient, auth_headers):
    r = client.post("/api/v1/printers/discover", json={"cidr": "0.0.0.0/0"},
                    headers=auth_headers)
    assert r.status_code == 400
