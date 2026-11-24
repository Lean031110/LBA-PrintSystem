"""Worker independiente de la cola de impresión.

Proceso systemd separado de la API (DADR-04): una impresora lenta no congela
el panel. Ciclo: claim atómico → render ESC/POS → envío TCP → estados.

Ejecutar: python -m app.worker [--once] [--verbose]
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import timedelta

from app.core import config
from app.database.db import get_sessionmaker, init_db, utcnow
from app.models import models
from app.services import preview, queue_service, rendering

log = logging.getLogger("lba.worker")

_STOP = False


def _handle_signal(signum, frame) -> None:  # pragma: no cover
    global _STOP
    _STOP = True
    log.info("señal %s recibida: terminando tras el trabajo en curso", signum)


def process_one(db) -> bool:
    """Procesa un trabajo. Devuelve True si se procesó algo."""
    job = queue_service.claim_next(db)
    if job is None:
        return False
    printer = db.get(models.Printer, job.printer_id)
    if printer is None or not printer.active:
        job.status = "failed"
        job.claim_expires_at = None
        job.last_error = "impresora inexistente o inactiva"
        db.commit()
        return True

    try:
        document = _to_document(job.payload)
        blob = rendering.render_document(
            printer, document,
            logo_b64=models.get_setting(db, "logo_b64"),
            columns=printer.columns)
        prev = preview.render_preview(blob,
                                       codec=printer.encoding or "AUTO",
                                       columns=printer.columns)
        queue_service.send_to_printer(printer, blob)
        queue_service.mark_sent(db, job, blob, prev)
        queue_service.touch_printer(db, printer, ok=True)
        db.commit()
        log.info("job %s → sent (%d bytes) a %s:%s",
                 job.id, len(blob), printer.ip, printer.port)
    except Exception as exc:
        queue_service.mark_attempt_failed(db, job, f"{type(exc).__name__}: {exc}")
        queue_service.touch_printer(db, printer, ok=False,
                                    err=f"{type(exc).__name__}: {exc}")
        db.commit()
        log.warning("job %s falló (intento %s/%s): %s",
                    job.id, job.attempts, job.max_attempts, exc)
    return True


def _to_document(payload: dict):
    from app.schemas import schemas as Schemas
    return Schemas.TicketDocument.model_validate(payload)


def healthcheck_printers(db) -> None:
    """Ping TCP suave de impresoras activas (estado online/offline)."""
    import socket as _socket
    for p in db.query(models.Printer).filter(models.Printer.active == 1).all():
        try:
            with _socket.create_connection((p.ip, p.port),
                                            timeout=2.0):
                p.status = "online"
                p.last_error = ""
        except OSError as exc:
            p.status = "offline"
            p.last_error = f"healthcheck: {exc}"
        p.last_seen_at = utcnow()
    db.commit()


def run(once: bool = False, verbose: bool = False) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    init_db()
    Session = get_sessionmaker()

    with Session() as db:
        orphans = models.recover_orphan_processing(db)
        if orphans:
            log.info("recuperados %d trabajos 'processing' huérfanos", orphans)
        db.commit()

    last_healthcheck = 0.0
    processed = 0
    while not _STOP:
        did = False
        with Session() as db:
            did = process_one(db)
            if did:
                processed += 1
        if not did:
            now = time.monotonic()
            if now - last_healthcheck >= config.WORKER_HEALTHCHECK_S:
                with Session() as db:
                    healthcheck_printers(db)
                last_healthcheck = now
            time.sleep(config.WORKER_POLL_S)
        if once:
            break
    log.info("worker finalizado (trabajos procesados en sesión: %d)", processed)
    return 0


def main() -> None:  # pragma: no cover (CLI)
    parser = argparse.ArgumentParser(description="Worker de la cola LBA")
    parser.add_argument("--once", action="store_true",
                        help="procesa un solo trabajo (tests/CI)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    sys.exit(run(once=args.once, verbose=args.verbose))


if __name__ == "__main__":  # pragma: no cover
    main()
