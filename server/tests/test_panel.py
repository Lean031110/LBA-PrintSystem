"""Panel web: login, secciones, alta de impresora y ticket de prueba."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_fallo_401(client: TestClient):
    r = client.post("/login", data={"password": "incorrecta"},
                    follow_redirects=False)
    assert r.status_code == 401


def test_login_ok_y_secciones(client: TestClient):
    r = client.post("/login", data={"password": "admin1234"},
                    follow_redirects=False)
    assert r.status_code == 303
    cookie = r.headers.get("set-cookie")
    assert cookie and "lba_session" in cookie

    for path in ("/", "/devices", "/discover", "/test_print", "/queue",
                 "/history", "/errors", "/settings", "/security"):
        rr = client.get(path)
        assert rr.status_code == 200, path
        assert "LBA" in rr.text


def test_login_requerido_redirige():
    from app.main import app
    with TestClient(app, follow_redirects=False) as anon:
        r = anon.get("/")
        assert r.status_code == 303
        assert "/login" in r.headers["location"]


def test_alta_de_impresora_por_formulario(client: TestClient):
    client.post("/login", data={"password": "admin1234"})
    r = client.post("/devices/add", data={
        "name": "Cocina", "ip": "127.0.0.1", "port": "9910",
        "manufacturer": "Rongta", "model": "RP326",
        "profile": "generic", "paper_width_mm": "80",
        "encoding": "CP850", "notes": "tests",
    }, follow_redirects=False)
    assert r.status_code == 303
    body = client.get("/devices").text
    assert "Cocina" in body and "RP326" in body


def test_alta_ip_publica_rechazada_por_panel(client: TestClient):
    client.post("/login", data={"password": "admin1234"})
    r = client.post("/devices/add", data={
        "name": "Mala", "ip": "8.8.8.8", "port": "9100",
        "paper_width_mm": "80", "encoding": "CP850",
    }, follow_redirects=False)
    assert r.status_code == 303            # con flash de error
    assert "Mala" not in client.get("/devices").text


def test_editar_impresora_panel_conserva_settings_logo(client: TestClient, db,
                                                       auth_headers):
    from app.models import models
    client.post("/login", data={"password": "admin1234"})
    created = client.post("/api/v1/printers", headers=auth_headers, json={
        "name": "EditarPanel", "ip": "127.0.0.1", "port": 9910,
        "profile": "simulator", "settings": {"logo": True},
    })
    assert created.status_code == 201
    pid = created.json()["id"]
    p = db.get(models.Printer, pid)
    p.settings = {**p.settings, "logo": True}
    db.commit()

    response = client.post(f"/devices/{pid}", data={
        "name": "Editada", "ip": "127.0.0.1", "port": "9910",
        "manufacturer": "", "model": "", "profile": "simulator",
        "paper_width_mm": "80", "encoding": "CP850", "notes": "",
        "active": "true", "cut": "true", "feed_before_cut": "3",
        "density": "-99", "qr_size": "6",
    }, follow_redirects=False)
    assert response.status_code == 303
    db.refresh(p)
    assert p.name == "Editada"
    assert p.settings["logo"] is True


def test_borrado_panel_archiva_impresora_con_historial(client: TestClient,
                                                       auth_headers):
    client.post("/login", data={"password": "admin1234"})
    created = client.post("/api/v1/printers", headers=auth_headers, json={
        "name": "HistPanel", "ip": "127.0.0.1", "port": 9910,
        "profile": "simulator",
    })
    pid = created.json()["id"]
    payload = {"printer_id": pid, "document": {"type": "ticket",
               "blocks": [{"type": "text", "value": "historial panel"}]}}
    queued = client.post("/api/v1/jobs", headers=auth_headers, json=payload)
    jid = queued.json()["id"]
    assert client.post(f"/api/v1/jobs/{jid}/cancel",
                       headers=auth_headers).status_code == 200

    removed = client.post(f"/devices/{pid}/delete", follow_redirects=False)
    assert removed.status_code == 303
    assert "HistPanel" not in client.get(removed.headers["location"]).text
    assert client.get(f"/api/v1/jobs/{jid}", headers=auth_headers).json()["status"] == "cancelled"
    assert client.get(f"/api/v1/printers/{pid}", headers=auth_headers).status_code == 404


def test_discovery_panel_obedece_rangos_guardados(client: TestClient, db,
                                                   monkeypatch):
    from app.models import models
    from app.services import discovery
    client.post("/login", data={"password": "admin1234"})
    models.set_setting(db, "discovery_ranges", ["192.168.30.0/24"])
    db.commit()
    called = False

    async def no_scan(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("no debe iniciar el escaneo")

    monkeypatch.setattr(discovery, "scan", no_scan)
    response = client.post("/discover", data={"cidr": "192.168.31.0/24",
                                              "ports": "9100"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/discover"
    assert called is False


def test_ticket_de_prueba_encola(client: TestClient):
    client.post("/login", data={"password": "admin1234"})
    # alta + prueba
    client.post("/devices/add", data={
        "name": "PruebaTicket", "ip": "127.0.0.1", "port": "9910",
        "profile": "simulator", "paper_width_mm": "80", "encoding": "CP850"})
    devices = client.get("/devices").text
    assert "PruebaTicket" in devices
    r = client.post("/test_print", data={"printer_id": _find_id(client),
                                         "kind": "caracteres"},
                    follow_redirects=False)
    assert r.status_code == 303
    queue = client.get("/queue").text
    assert "test" in queue


def _find_id(client: TestClient) -> str:
    import re
    m = re.search(r'/devices/([0-9a-f-]{36})', client.get("/devices").text)
    return m.group(1)
