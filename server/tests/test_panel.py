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
