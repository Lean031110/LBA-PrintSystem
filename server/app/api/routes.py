"""API REST /api/v1 (FastAPI). OpenAPI automática en /docs y /redoc."""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import deps
from app.core import config
from app.database.db import get_db, utcnow
from app.models import models
from app.printer_profiles import profiles as PP
from app.schemas import schemas as S
from app.services import discovery, queue_service, rendering

router = APIRouter(prefix="/api/v1", tags=["api-v1"])
_STARTED_AT = time.monotonic()


# ------------------------------------------------------------- serialización

def printer_out(db: Session, p: models.Printer) -> dict:
    jobs_sent = (db.query(models.Job)
                 .filter(models.Job.printer_id == p.id,
                         models.Job.status == "sent").count())
    return {
        "id": p.id, "name": p.name, "manufacturer": p.manufacturer,
        "model": p.model, "profile": p.profile,
        "connection_type": p.connection_type, "protocol": p.protocol,
        "ip": p.ip, "port": p.port, "paper_width_mm": p.paper_width_mm,
        "columns": p.columns, "encoding": p.encoding, "status": p.status,
        "last_seen_at": p.last_seen_at.isoformat() + "Z" if p.last_seen_at else None,
        "last_error": p.last_error or "",
        "notes": p.notes or "", "active": bool(p.active),
        "settings": p.settings or {},
        "jobs_sent": jobs_sent,
        "created_at": p.created_at.isoformat() + "Z",
    }


def job_out(db: Session, j: models.Job, with_preview: bool = False,
           printer: Optional[models.Printer] = None) -> dict:
    p = printer or db.get(models.Printer, j.printer_id)
    out = {
        "id": j.id, "printer_id": j.printer_id,
        "printer_name": p.name if p else None,
        "status": j.status, "attempts": j.attempts,
        "max_attempts": j.max_attempts, "idempotency_key": j.idempotency_key,
        "origin": j.origin, "metadata": j.meta or {},
        "created_at": j.created_at.isoformat() + "Z",
        "updated_at": j.updated_at.isoformat() + "Z",
        "sent_at": j.sent_at.isoformat() + "Z" if j.sent_at else None,
        "next_attempt_at": j.next_attempt_at.isoformat() + "Z",
        "last_error": j.last_error or "",
        "bytes_len": j.bytes_len or 0,
        "has_preview": bool(j.preview_text),
    }
    if with_preview:
        out["preview"] = j.preview_text or ""
    return out


# ------------------------------------------------------------------- health

@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    # Readiness: require the application schema to be queryable. Keep public
    # output minimal; database details and operational data are not exposed.
    try:
        db.execute(text("SELECT 1 FROM jobs LIMIT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {
        "status": "ok", "app": config.APP_NAME, "version": config.APP_VERSION,
        "uptime_s": int(time.monotonic() - _STARTED_AT),
    }


@router.get("/stats", dependencies=[Depends(deps.api_auth)])
def stats(db: Session = Depends(get_db)) -> dict:
    q = {s: db.query(models.Job).filter(models.Job.status == s).count()
         for s in ("pending", "processing", "sent", "failed", "cancelled")}
    per_printer = [
        {"printer_id": p.id, "name": p.name, "status": p.status,
         "last_seen_at": p.last_seen_at.isoformat() + "Z" if p.last_seen_at else None,
         "last_error": p.last_error}
        for p in db.query(models.Printer).filter(models.Printer.status != "deleted").all()
    ]
    return {"queue": q, "printers": per_printer,
            "uptime_s": int(time.monotonic() - _STARTED_AT)}


# ---------------------------------------------------------------- impresoras

@router.get("/printers", dependencies=[Depends(deps.api_auth)])
def list_printers(db: Session = Depends(get_db)) -> dict:
    items = [printer_out(db, p)
             for p in db.query(models.Printer)
             .filter(models.Printer.status != "deleted")
             .order_by(models.Printer.created_at).all()]
    return {"items": items, "count": len(items)}


@router.post("/printers", status_code=201,
             dependencies=[Depends(deps.api_auth)])
def create_printer(body: S.PrinterCreate, request: Request,
                   db: Session = Depends(get_db)) -> dict:
    allow_public = bool(models.get_setting(db, "allow_public_printer_ips", False))
    ok, why = deps.security.printer_ip_allowed(body.ip, allow_public)
    if not ok:
        raise HTTPException(400, f"IP de impresora rechazada: {why}")
    p = models.Printer(
        name=body.name, manufacturer=body.manufacturer, model=body.model,
        profile=body.profile, ip=body.ip, port=body.port,
        paper_width_mm=body.paper_width_mm,
        columns=32 if body.paper_width_mm == 58 else 48,
        encoding=body.encoding, notes=body.notes,
        active=1 if body.active else 0,
        settings=body.settings.model_dump(),
    )
    db.add(p)
    db.flush()
    models.audit(db, deps.security.get_client_ip(request), "api",
                 "printer.create", {"id": p.id, "name": p.name, "ip": p.ip})
    db.commit()
    return printer_out(db, p)


def _get_printer(db: Session, printer_id: str) -> models.Printer:
    p = db.get(models.Printer, printer_id)
    if p is None or p.status == "deleted":
        raise HTTPException(404, "impresora no encontrada")
    return p


@router.get("/printers/{printer_id}", dependencies=[Depends(deps.api_auth)])
def get_printer(printer_id: str, db: Session = Depends(get_db)) -> dict:
    return printer_out(db, _get_printer(db, printer_id))


@router.put("/printers/{printer_id}", dependencies=[Depends(deps.api_auth)])
def update_printer(printer_id: str, body: S.PrinterUpdate, request: Request,
                   db: Session = Depends(get_db)) -> dict:
    p = _get_printer(db, printer_id)
    data = body.model_dump(exclude_unset=True)
    if "ip" in data and data["ip"] and data["ip"] != p.ip:
        allow_public = bool(models.get_setting(db, "allow_public_printer_ips", False))
        ok, why = deps.security.printer_ip_allowed(data["ip"], allow_public)
        if not ok:
            raise HTTPException(400, f"IP de impresora rechazada: {why}")
    for k, v in data.items():
        if k == "settings":
            p.settings = v
        elif k == "active":
            p.active = 1 if v else 0
        elif k == "paper_width_mm":
            p.paper_width_mm = v
            p.columns = 32 if v == 58 else 48
        else:
            setattr(p, k, v)
    models.audit(db, deps.security.get_client_ip(request), "api",
                 "printer.update", {"id": p.id, "changes": list(data.keys())})
    db.commit()
    return printer_out(db, p)


@router.delete("/printers/{printer_id}", status_code=200,
               dependencies=[Depends(deps.api_auth)])
def delete_printer(printer_id: str, request: Request,
                   db: Session = Depends(get_db)) -> dict:
    p = _get_printer(db, printer_id)
    if (db.query(models.Job).filter(models.Job.printer_id == p.id,
                                    models.Job.status.in_(["pending", "processing"])).count()):
        raise HTTPException(409, "la impresora tiene trabajos en cola; "
                                 "cáncelalos o reinténtalos antes de borrar")
    has_history = db.query(models.Job.id).filter(
        models.Job.printer_id == p.id).first() is not None
    if has_history:
        models.archive_printer(db, p)
    else:
        db.delete(p)
    models.audit(db, deps.security.get_client_ip(request), "api",
                 "printer.delete", {"id": printer_id, "archived": has_history})
    db.commit()
    return {"deleted": printer_id, "archived": has_history}


@router.post("/printers/discover", dependencies=[Depends(deps.api_auth)])
async def discover_printers(body: S.DiscoverRequest, request: Request,
                            db: Session = Depends(get_db)) -> dict:
    try:
        discovery.validate_configured_range(
            body.cidr, models.get_setting(db, "discovery_ranges",
                                          config.DEFAULT_DISCOVERY_RANGES))
        found = await discovery.scan(body.cidr, body.ports)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    models.audit(db, deps.security.get_client_ip(request), "api",
                 "printers.discover", {"cidr": body.cidr, "found": len(found)})
    db.commit()
    return {"cidr": body.cidr, "found": found, "count": len(found)}


@router.post("/printers/{printer_id}/test", status_code=202,
             dependencies=[Depends(deps.api_auth)])
def printer_test(printer_id: str, body: S.TestPrintRequest,
                 request: Request, db: Session = Depends(get_db)) -> dict:
    p = _get_printer(db, printer_id)
    if not p.active:
        raise HTTPException(409, "impresora inactiva")
    company = models.get_setting(db, "company_name", "LBA")
    doc = rendering.test_ticket(p, body.kind, company,
                                models.get_setting(db, "logo_b64"))
    try:
        job, created = queue_service.enqueue(db, p, doc, origin="test",
                                             meta={"kind": body.kind})
    except OperationalError as exc:
        db.rollback()
        raise HTTPException(503, "base de datos ocupada; vuelva a intentar") from exc
    db.commit()
    out = job_out(db, job)
    out["duplicate"] = not created
    return out


# ------------------------------------------------------------------ trabajos

@router.post("/jobs", status_code=202, dependencies=[Depends(deps.api_auth)])
def create_job(body: S.JobCreate, request: Request,
               db: Session = Depends(get_db)) -> dict:
    p = _get_printer(db, body.printer_id)
    if not p.active:
        raise HTTPException(409, "impresora inactiva")
    try:
        job, created = queue_service.enqueue(db, p, body.document,
                                             origin=body.origin,
                                             idempotency_key=body.idempotency_key,
                                             meta=body.metadata)
    except OperationalError as exc:
        db.rollback()
        raise HTTPException(
            503, "base de datos ocupada; reintente con la misma clave idempotente"
        ) from exc
    except queue_service.IdempotencyKeyConflict as exc:
        raise HTTPException(409, str(exc))
    except rendering.RenderError as exc:
        raise HTTPException(400, f"payload no imprimible: {exc}")
    db.commit()
    out = job_out(db, job)
    out["duplicate"] = not created
    if not created:
        raise HTTPException(409, detail={"message": "idempotencia: el trabajo ya "
                                                    "existe", "job": out})
    return out


@router.get("/jobs", dependencies=[Depends(deps.api_auth)])
def list_jobs(status: Optional[str] = None, printer_id: Optional[str] = None,
               limit: int = 50, offset: int = 0,
               db: Session = Depends(get_db)) -> dict:
    limit = max(1, min(limit, 500))
    q = db.query(models.Job)
    if status:
        if status not in ("pending", "processing", "sent", "failed", "cancelled"):
            raise HTTPException(400, "status inválido")
        q = q.filter(models.Job.status == status)
    if printer_id:
        q = q.filter(models.Job.printer_id == printer_id)
    total = q.count()
    items = [job_out(db, j)
            for j in q.order_by(models.Job.created_at.desc())
            .offset(offset).limit(limit).all()]
    return {"items": items, "count": total, "limit": limit, "offset": offset}


def _get_job(db: Session, job_id: str) -> models.Job:
    j = db.get(models.Job, job_id)
    if j is None:
        raise HTTPException(404, "trabajo no encontrado")
    return j


@router.get("/jobs/{job_id}", dependencies=[Depends(deps.api_auth)])
def get_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    j = _get_job(db, job_id)
    events = [{"ts": e.ts.isoformat() + "Z", "from": e.from_status,
               "to": e.to_status, "detail": e.detail}
              for e in db.query(models.JobEvent)
              .filter(models.JobEvent.job_id == j.id)
              .order_by(models.JobEvent.ts).all()]
    out = job_out(db, j, with_preview=True)
    out["events"] = events
    return out


@router.post("/jobs/{job_id}/retry", dependencies=[Depends(deps.api_auth)])
def retry_job(job_id: str, request: Request,
              db: Session = Depends(get_db)) -> dict:
    j = _get_job(db, job_id)
    if not queue_service.retry(db, j):
        raise HTTPException(409, f"no se puede reintentar en estado {j.status}")
    models.audit(db, deps.security.get_client_ip(request), "api",
                 "job.retry", {"id": job_id})
    db.commit()
    return job_out(db, j)


@router.post("/jobs/{job_id}/reprint", status_code=202,
             dependencies=[Depends(deps.api_auth)])
def reprint_job(job_id: str, request: Request,
                db: Session = Depends(get_db)) -> dict:
    j = _get_job(db, job_id)
    try:
        new = queue_service.reprint(db, j)
    except queue_service.PrinterUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    models.audit(db, deps.security.get_client_ip(request), "api",
                 "job.reprint", {"id": job_id, "new_id": new.id})
    db.commit()
    return job_out(db, new)


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(deps.api_auth)])
def cancel_job(job_id: str, request: Request,
               db: Session = Depends(get_db)) -> dict:
    j = _get_job(db, job_id)
    if not queue_service.cancel(db, j):
        raise HTTPException(409, f"no se puede cancelar en estado {j.status}")
    models.audit(db, deps.security.get_client_ip(request), "api",
                 "job.cancel", {"id": job_id})
    db.commit()
    return job_out(db, j)


# ---------------------------------------------------------------- purga

@router.post("/maintenance/purge", dependencies=[Depends(deps.api_auth)])
def purge(request: Request, db: Session = Depends(get_db)) -> dict:
    days = int(models.get_setting(db, "retention_days",
                                   config.RETENTION_DAYS_DEFAULT))
    n = models.purge_expired(db, days)
    models.audit(db, deps.security.get_client_ip(request), "api",
                 "maintenance.purge", {"deleted": n, "days": days})
    db.commit()
    return {"deleted": n, "retention_days": days}
