"""Cola persistente: alta idempotente, claim atómico, reintentos, historial."""
from __future__ import annotations

import base64
import socket
from datetime import timedelta
from typing import Optional

from sqlalchemy import text

from app.core import config
from app.database.db import get_engine, get_sessionmaker, utcnow
from app.models.models import Job, JobEvent, Printer
from app.schemas import schemas as S


# ------------------------------------------------------------------- alta

def enqueue(db, printer: Printer, document: S.TicketDocument, origin: str,
            idempotency_key: Optional[str] = None,
            meta: Optional[dict] = None) -> tuple[Job, bool]:
    """Crea un trabajo. Devuelve (job, creado). Si la clave idempotente ya
    existe, devuelve el trabajo existente y NO crea otro (duplicado=evitado)."""
    if idempotency_key:
        existing = (db.query(Job)
                      .filter(Job.idempotency_key == idempotency_key)
                      .first())
        if existing is not None:
            return existing, False
    job = Job(printer_id=printer.id, payload=document.model_dump(),
             origin=origin, meta=meta or {},
             idempotency_key=idempotency_key,
             max_attempts=printer.settings.get("max_attempts",
                                               config.MAX_ATTEMPTS_DEFAULT)
             if isinstance(printer.settings, dict) else config.MAX_ATTEMPTS_DEFAULT)
    db.add(job)
    db.flush()
    db.add(JobEvent(job_id=job.id, from_status="", to_status="pending",
                    detail=f"encolado origin={origin}"
                           f"{' key=' + idempotency_key if idempotency_key else ''}"))
    return job, True


def retry(db, job: Job) -> bool:
    if job.status not in ("failed", "pending", "cancelled"):
        return False
    old = job.status
    job.status = "pending"
    job.attempts = 0
    job.next_attempt_at = utcnow()
    job.last_error = ""
    db.add(JobEvent(job_id=job.id, from_status=old, to_status="pending",
                    detail="reintento manual"))
    return True


def reprint(db, job: Job) -> Job:
    """Reimpresión: SIEMPRE un trabajo nuevo (histórico fiel), sin key."""
    payload = dict(job.payload or {})
    new = Job(printer_id=job.printer_id, payload=payload, origin="reprint",
              meta={"reprint_of": job.id}, idempotency_key=None,
              max_attempts=job.max_attempts)
    db.add(new)
    db.flush()
    db.add(JobEvent(job_id=new.id, from_status="", to_status="pending",
                    detail=f"reimpresión de {job.id}"))
    return new


def cancel(db, job: Job) -> bool:
    if job.status != "pending":
        return False
    job.status = "cancelled"
    db.add(JobEvent(job_id=job.id, from_status="pending",
                    to_status="cancelled", detail="cancelado manualmente"))
    return True


# ----------------------------------------------------------------- worker

def claim_next(db) -> Optional[Job]:
    """Claim atómico (UPDATE condicionado) del siguiente trabajo elegible.

    SQLite es single-writer: la condición de estado en el WHERE garantiza
    que dos workers (o worker+retry de API) no procesen el mismo job.
    """
    with get_engine().begin() as conn:
        row = conn.execute(text(
            "SELECT id FROM jobs WHERE status = 'pending' "
            "AND next_attempt_at <= :now "
            "ORDER BY priority ASC, created_at ASC LIMIT 1"
        ), {"now": utcnow()}).fetchone()
        if row is None:
            return None
        res = conn.execute(text(
            "UPDATE jobs SET status='processing', updated_at=:now "
            "WHERE id=:id AND status='pending'"
        ), {"id": row[0], "now": utcnow()})
        if res.rowcount != 1:
            return None
    job = db.get(Job, row[0])
    if job is not None:
        # CRÍTICO: el claim se hizo por conexión directa (UPDATE) y la sesión
        # ORM puede tener el objeto en caché con estado anterior. refrescamos
        # para que el identity map vea 'processing' y los cambios posteriores
        # (pending/sent/failed) sí generen UPDATE.
        db.refresh(job)
        db.add(JobEvent(job_id=job.id, from_status="pending",
                        to_status="processing", detail="claim del worker"))
    return job


def backoff_seconds(attempts: int) -> int:
    return min(config.BACKOFF_BASE_S * (2 ** max(0, attempts - 1)),
               config.BACKOFF_MAX_S)


def mark_sent(db, job: Job, blob: bytes, preview: str) -> None:
    job.status = "sent"
    job.sent_at = utcnow()
    job.attempts += 1
    job.last_error = ""
    job.bytes_len = len(blob)
    job.bytes_hex = blob.hex()
    job.preview_text = preview
    db.add(JobEvent(job_id=job.id, from_status="processing", to_status="sent",
                    detail=f"bytes={len(blob)} enviados al socket"))


def mark_attempt_failed(db, job: Job, err: str) -> None:
    job.attempts += 1
    job.last_error = (err or "")[:2000]
    if job.attempts >= job.max_attempts:
        job.status = "failed"
        db.add(JobEvent(job_id=job.id, from_status="processing",
                        to_status="failed", detail=job.last_error[:500]))
    else:
        job.status = "pending"
        job.next_attempt_at = utcnow() + timedelta(
            seconds=backoff_seconds(job.attempts))
        db.add(JobEvent(job_id=job.id, from_status="processing",
                        to_status="pending",
                        detail=f"intento {job.attempts}/{job.max_attempts} falló; "
                               f"siguiente en {backoff_seconds(job.attempts)}s: "
                               f"{job.last_error[:300]}"))


# ------------------------------------------------------------- envío TCP

def send_to_printer(printer: Printer, blob: bytes) -> None:
    """Envía bytes por TCP raw. Lanza excepción si falla (nunca 'impreso')."""
    timeout = config.SOCKET_TIMEOUT_S
    with socket.create_connection((printer.ip, printer.port),
                                  timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(blob)
        # medio cierre para que los firmwares de clon procesen el buffer
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            sock.recv(64)  # drenar posibles bytes de estado y liberar
        except (socket.timeout, OSError):
            pass


def touch_printer(db, printer: Printer, ok: bool, err: str = "") -> None:
    printer.status = "online" if ok else "offline"
    printer.last_seen_at = utcnow()
    printer.last_error = (err or "")[:2000]
