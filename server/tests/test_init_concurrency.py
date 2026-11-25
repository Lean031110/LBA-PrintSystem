"""Regresiones de inicialización concurrente de SQLite.

La API y el worker pueden arrancar a la vez sobre una base nueva (contenedor
Docker, dos servicios recién instalados). Antes, el segundo proceso abortaba
con ``UNIQUE constraint failed: settings.key`` y el servicio no arrancaba.
"""
from __future__ import annotations

from unittest import mock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.database import db as database


def test_init_db_reintenta_tras_colision_de_ajustes() -> None:
    from app.models import models

    real = models.ensure_default_settings
    calls = {"n": 0}

    def flaky(session):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("INSERT INTO settings", {}, Exception("UNIQUE"))
        return real(session)

    with mock.patch.object(models, "ensure_default_settings", side_effect=flaky):
        database.init_db()

    assert calls["n"] >= 2


def test_init_db_tolera_bloqueo_de_escritura_y_reintenta() -> None:
    from app.models import models

    real = models.ensure_default_settings
    calls = {"n": 0}

    def locked(session):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("INSERT INTO settings", {}, Exception("locked"))
        return real(session)

    with mock.patch.object(models, "ensure_default_settings", side_effect=locked):
        database.init_db()

    assert calls["n"] >= 2


def test_init_db_propaga_el_error_si_no_hay_ajustes_sembrados() -> None:
    from app.models import models

    error = OperationalError("INSERT INTO settings", {}, Exception("disk I/O"))

    with mock.patch.object(models, "ensure_default_settings", side_effect=error), \
            mock.patch.object(models, "get_setting", return_value=None), \
            mock.patch.object(database.time, "sleep", return_value=None):
        with pytest.raises(OperationalError):
            database.init_db()
