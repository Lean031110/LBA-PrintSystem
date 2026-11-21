"""Worker: envío real por TCP al simulador, reintentos y reCAP tras reinicio."""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database.db import get_sessionmaker, utcnow
from app.models import models
from app.schemas import schemas as S
from app.services import queue_service
from app.worker.__main__ import process_one


@pytest.fixture(autouse=True)
def _limpiar_cola(db):
    """Aislamiento: esta suite comparte BD con las demás; vaciamos la cola."""
    db.query(models.JobEvent).delete()
    db.query(models.Job).delete()
    db.commit()
    yield


def _add_printer(db, name, ip, port, profile="simulator"):
    p = models.Printer(name=name, ip=ip, port=port, profile=profile,
                       paper_width_mm=80, columns=48, encoding="CP850",
                       settings={"cut": True, "feed_before_cut": 3, "qr_size": 6})
    db.add(p)
    db.commit()
    return p


def _doc():
    return S.TicketDocument.model_validate({"type": "ticket", "blocks": [
        {"type": "text", "value": "COMANDA — Mesa 4 ñá", "bold": True},
        {"type": "text", "value": "2 x Pizza Especial"},
        {"type": "ruler"},
        {"type": "qr", "value": "order:00042", "size": 6},
        {"type": "cut"},
    ]})


def test_envio_completo_a_simulador(db, simulator):
    from app.drivers import simulator as sim
    p = _add_printer(db, "E2E-Sim", "127.0.0.1", simulator)
    job, created = queue_service.enqueue(db, p, _doc(), origin="test")
    db.commit()

    assert process_one(db) is True
    db.refresh(job)
    assert job.status == "sent"                      # enviado, no 'printed'
    assert job.bytes_len > 100
    assert job.preview_text and "COMANDA" in job.preview_text
    assert job.sent_at is not None
    assert len(sim.last_documents()) >= 1
    # la impresora queda 'online'
    db.refresh(p)
    assert p.status == "online"
    assert p.last_seen_at is not None


def test_reintentos_backoff_y_failed(db):
    # puerto 1 en localhost: conexión rechazada al instante
    p = _add_printer(db, "E2E-Dead", "127.0.0.1", 1, profile="generic")
    job, _ = queue_service.enqueue(db, p, _doc(), origin="test")
    db.commit()

    for i in range(5):
        assert process_one(db) is True
        db.refresh(job)
        if job.status == "failed":
            break
        assert job.status == "pending"
        assert job.attempts == i + 1
        # backoff creciente: next_attempt en el futuro...
        assert job.next_attempt_at > utcnow()
        # ...simulamos el paso del tiempo para el siguiente intento
        job.next_attempt_at = utcnow()
        db.commit()

    assert job.status == "failed"
    assert job.attempts == job.max_attempts
    assert job.last_error
    # eventos registrados
    evts = (db.query(models.JobEvent)
            .filter(models.JobEvent.job_id == job.id).all())
    assert len(evts) >= job.max_attempts + 1


def test_retry_manual_resetea(db):
    p = _add_printer(db, "E2E-Retry", "127.0.0.1", 1, profile="generic")
    job, _ = queue_service.enqueue(db, p, _doc(), origin="test")
    db.commit()
    for _ in range(5):
        process_one(db)
        db.refresh(job)
        if job.status == "failed":
            break
        job.next_attempt_at = utcnow()   # simula el paso del backoff
        db.commit()
    db.refresh(job)
    assert job.status == "failed"
    assert queue_service.retry(db, job) is True
    db.commit()
    db.refresh(job)
    assert job.status == "pending"
    assert job.attempts == 0


def test_recuperacion_tras_reinicio(db):
    """Trabajos 'processing' huérfanos (crash del worker) vuelven a pending."""
    p = _add_printer(db, "E2E-Orphan", "127.0.0.1", 1)
    job, _ = queue_service.enqueue(db, p, _doc(), origin="test")
    db.commit()
    job.status = "processing"          # simula worker muerto a mitad
    db.commit()
    n = models.recover_orphan_processing(db)
    db.commit()
    assert n >= 1
    db.refresh(job)
    assert job.status == "pending"


def test_claim_no_duplica_con_current_session(db):
    """El claim con UPDATE condicionado evita doble proceso."""
    p = _add_printer(db, "E2E-Claim", "127.0.0.1", 1)
    for _ in range(3):
        queue_service.enqueue(db, p, _doc(), origin="test")
    db.commit()
    # dos sesiones distintas reclaman secuencialmente jobs distintos
    s1 = get_sessionmaker()()
    j1 = queue_service.claim_next(s1)
    s2 = get_sessionmaker()()
    j2 = queue_service.claim_next(s2)
    assert j1.id != j2.id
    s1.close()
    s2.close()
