"""Fixtures: entorno aislado (BD temporal), API con TestClient y simulador."""
from __future__ import annotations

import os
import tempfile

# Entorno ANTES de importar la app (config se lee al importar).
_TMP = tempfile.mkdtemp(prefix="lba-test-")
os.environ["LBA_DATA_DIR"] = _TMP
os.environ["LBA_ADMIN_PASSWORD"] = "admin1234"
os.environ["LBA_API_TOKEN"] = "lba_testtoken123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    """Crea tablas/ajustes aunque el test no use la app (p.ej. worker)."""
    from app.database.db import init_db
    init_db()


@pytest.fixture(scope="session")
def client() -> TestClient:
    # client= fija la IP del socket de prueba → allowlist la acepta
    with TestClient(app, client=("127.0.0.1", 60000)) as c:
        # límites holgados para la suite (se prueban aparte, con límite bajo)
        from app.database.db import get_sessionmaker
        from app.models import models
        s = get_sessionmaker()()
        models.set_setting(s, "api_rate_limit", {"limit": 100000, "window_s": 60})
        models.set_setting(s, "login_rate_limit", {"limit": 100000, "window_s": 60})
        s.commit()
        s.close()
        yield c


@pytest.fixture(scope="session")
def token() -> str:
    return os.environ["LBA_API_TOKEN"]


@pytest.fixture(scope="session")
def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def simulator():
    """Simulador ESC/POS en puerto efímero; devuelve (puerto, cleanup)."""
    from app.drivers import simulator as sim
    srv = sim.start("127.0.0.1", 0, echo=False)
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()
    sim.RECEIVED.clear()


@pytest.fixture()
def db():
    from app.database.db import get_sessionmaker
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()
