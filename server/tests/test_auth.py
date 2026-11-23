"""Autenticación de la API: token, IP allowlist, rate limit, /health pública."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_publico(client: TestClient):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["app"] == "LBA Print Server"
    # /health no expone secretos
    assert "token" not in r.text.lower()
    assert set(body) == {"status", "app", "version", "uptime_s"}
    assert "printers" not in body and "queue" not in body


def test_health_no_disponible_si_sqlite_no_esta_lista(client: TestClient):
    from sqlalchemy.exc import OperationalError
    from app.database.db import get_db

    class UnavailableSession:
        def execute(self, *_args, **_kwargs):
            raise OperationalError("SELECT", {}, RuntimeError("offline"))

    def failing_db():
        yield UnavailableSession()

    app = client.app
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = failing_db
    try:
        response = client.get("/api/v1/health")
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


def test_sin_token_401(client: TestClient):
    assert client.get("/api/v1/printers").status_code == 401


def test_token_invalido_401_y_auditoria_persistida(client: TestClient, db):
    from app.models.models import AuditLog

    r = client.get("/api/v1/printers", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    event = db.query(AuditLog).filter(AuditLog.action == "token.invalid").order_by(
        AuditLog.id.desc()).first()
    assert event is not None
    assert event.detail == {"path": "/api/v1/printers"}
    assert "nope" not in str(event.detail)


def test_ip_no_autorizada_403(client: TestClient, token: str):
    # la allowlist por defecto no incluye 8.8.8.8 → 403 (no 401)
    with TestClient(app := client.app, client=("8.8.8.8", 40000)) as otro:
        r = otro.get("/api/v1/printers", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403


def test_openapi_disponible(client: TestClient):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    for p in ("/api/v1/health", "/api/v1/printers", "/api/v1/jobs",
              "/api/v1/jobs/{job_id}/retry", "/api/v1/jobs/{job_id}/reprint",
              "/api/v1/printers/discover", "/api/v1/printers/{printer_id}/test"):
        assert p in paths, p


def test_rate_limit_429(client: TestClient, auth_headers, db):
    """Con límite bajo (5/min) la 6ª petición recibe 429; luego se restaura."""
    from app.models import models as M
    M.set_setting(db, "api_rate_limit", {"limit": 5, "window_s": 60})
    db.commit()
    codes = [client.get("/api/v1/stats", headers=auth_headers).status_code
             for _ in range(10)]
    assert 429 in codes
    M.set_setting(db, "api_rate_limit", {"limit": 100000, "window_s": 60})
    db.commit()
