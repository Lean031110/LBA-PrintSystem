"""Persistencia SQLite: la cola sobrevive a reinicios de proceso."""
from __future__ import annotations

import os

from app.database.db import get_engine, get_sessionmaker
from app.models import models
from app.schemas import schemas as S
from app.services import queue_service


def _doc():
    return S.TicketDocument.model_validate(
        {"type": "ticket",
         "blocks": [{"type": "text", "value": "persistente ñ"}]})


def _add_printer(db):
    p = models.Printer(name="Persist", ip="127.0.0.1", port=9910,
                       profile="simulator", encoding="CP850")
    db.add(p)
    db.commit()
    return p


def test_jobs_persisten_tras_reconexion():
    db = get_sessionmaker()()
    p = _add_printer(db)
    job, _ = queue_service.enqueue(db, p, _doc(), origin="test")
    db.commit()
    jid, pid = job.id, p.id
    db.close()

    # simular reinicio: nueva sesión sobre el mismo archivo SQLite
    db2 = get_sessionmaker()()
    job2 = db2.get(models.Job, jid)
    assert job2 is not None
    assert job2.status == "pending"
    assert job2.payload["blocks"][0]["value"] == "persistente ñ"
    p2 = db2.get(models.Printer, pid)
    assert p2.name == "Persist"
    db2.close()


def test_wal_activado():
    import sqlite3
    from app.core import config
    con = sqlite3.connect(str(config.DB_PATH))
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    con.close()
    assert mode.lower() == "wal"


def test_purga_retencion():
    from datetime import timedelta
    from app.database.db import utcnow
    db = get_sessionmaker()()
    p = _add_printer(db)
    job, _ = queue_service.enqueue(db, p, _doc(), origin="test")
    job.status = "sent"
    job.created_at = utcnow() - timedelta(days=40)
    db.commit()
    n = models.purge_expired(db, 30)
    db.commit()
    assert n >= 1
    assert db.get(models.Job, job.id) is None
    db.close()
