"""Panel web del LBA Print Server (HTML + HTMX vendorizado, tema oscuro).

Autenticación: usuario admin único, cookie firmada (itsdangerous).
Todas las secciones de FASE 2: Dashboard, Dispositivos, Búsqueda,
Configuración, Prueba, Cola, Historial, Errores, Configuración, Seguridad.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api import deps
from app.core import config, security
from app.database.db import get_db, init_db, utcnow
from app.models import models
from app.schemas import schemas as S
from app.services import discovery, queue_service, rendering

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["APP_NAME"] = config.APP_NAME
templates.env.globals["APP_VERSION"] = config.APP_VERSION

router = APIRouter(include_in_schema=False)
signer = security.SessionSigner(config.get_or_create_secret())


# ------------------------------------------------------------------ helpers

def _flash(request: Request, msg: str, kind: str = "ok") -> None:
    request.session_flash = {"msg": msg, "kind": kind}  # type: ignore[attr-defined]


def _render(request: Request, db: Session, template: str, extra: dict,
            status: int = 200) -> HTMLResponse:
    flash = getattr(request, "session_flash", None)
    admin = getattr(request, "admin_ok", False)
    ctx = {
        "request": request, "flash": flash, "admin": admin,
        "queue_counts": _queue_counts(db),
        "section": template.split("/")[-1].replace(".html", ""),
    }
    ctx.update(extra)
    return templates.TemplateResponse(request, template, ctx, status_code=status)


def _queue_counts(db: Session) -> dict:
    return {s: db.query(models.Job).filter(models.Job.status == s).count()
            for s in ("pending", "processing", "sent", "failed", "cancelled")}


def _admin_redirect(request: Request) -> Optional[RedirectResponse]:
    """None si la sesión es válida; si no, redirige a /login."""
    token = request.cookies.get(config.COOKIE_NAME)
    if token:
        sub = signer.verify(token, config.SESSION_TTL_S)
        if sub == "admin":
            request.admin_ok = True  # type: ignore[attr-defined]
            return None
    return RedirectResponse("/login", status_code=303)


def _require(request: Request) -> Optional[RedirectResponse]:
    return _admin_redirect(request)


def _password_ok(db: Session, password: str) -> bool:
    stored = models.get_setting(db, "admin")
    return bool(stored) and security.verify_password(password, stored)


# ------------------------------------------------------------------- login

@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    if _admin_redirect(request) is None:
        return RedirectResponse("/", status_code=303)
    return _render(request, db, "login.html", {})


@router.post("/login")
def login_post(request: Request, password: str = Form(...),
               db: Session = Depends(get_db)):
    ip = security.get_client_ip(request)
    ok_rl, _ = security.rate_limiter.allow(
        f"login:{ip}", config.LOGIN_RATE_LIMIT["limit"],
        config.LOGIN_RATE_LIMIT["window_s"])
    if not ok_rl:
        request.session_flash = {"msg": "Demasiados intentos; espera un minuto.",
                                 "kind": "err"}  # type: ignore[attr-defined]
        return _render(request, db, "login.html", {}, status=429)
    if _password_ok(db, password):
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(config.COOKIE_NAME, signer.sign("admin"),
                        httponly=True, samesite="lax")
        models.audit(db, ip, "admin", "login.ok", {})
        db.commit()
        return resp
    models.audit(db, ip, "admin", "login.fail", {})
    db.commit()
    request.session_flash = {"msg": "Contraseña incorrecta.", "kind": "err"}  # type: ignore[attr-defined]
    return _render(request, db, "login.html", {}, status=401)


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(config.COOKIE_NAME)
    return resp


# ---------------------------------------------------------------- dashboard

@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    printers = db.query(models.Printer).order_by(models.Printer.name).all()
    last_jobs = (db.query(models.Job).order_by(models.Job.created_at.desc())
                 .limit(10).all())
    errors = (db.query(models.Job).filter(models.Job.status == "failed")
              .order_by(models.Job.updated_at.desc()).limit(5).all())
    return _render(request, db, "dashboard.html", {
        "printers": printers, "last_jobs": last_jobs, "errors": errors,
        "online": sum(1 for p in printers if p.status == "online"),
        "offline": sum(1 for p in printers if p.status == "offline"),
        "company": models.get_setting(db, "company_name", "LBA"),
    })


# -------------------------------------------------------------- dispositivos

@router.get("/devices")
def devices(request: Request, db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    items = db.query(models.Printer).order_by(models.Printer.created_at).all()
    return _render(request, db, "devices.html", {"printers": items})


def _create_printer_from_form(db, request, form: dict,
                              ip: str, port: int) -> Optional[str]:
    allow_public = bool(models.get_setting(db, "allow_public_printer_ips", False))
    ok, why = security.printer_ip_allowed(ip, allow_public)
    if not ok:
        return f"IP rechazada: {why}"
    p = models.Printer(
        name=form.get("name") or "Impresora",
        manufacturer=form.get("manufacturer", ""),
        model=form.get("model", ""),
        profile=form.get("profile", "generic"),
        ip=ip, port=port,
        paper_width_mm=int(form.get("paper_width_mm") or 80),
        encoding=form.get("encoding", config.DEFAULT_ENCODING),
        notes=form.get("notes", ""),
        active=1,
        settings={
            "cut": True, "feed_before_cut": 3, "density": None,
            "logo": False, "qr_size": 6,
        })
    p.columns = 32 if p.paper_width_mm == 58 else 48
    db.add(p)
    db.flush()
    models.audit(db, security.get_client_ip(request), "admin",
                 "printer.create", {"id": p.id, "name": p.name, "ip": ip})
    db.commit()
    return None


@router.post("/devices/add")
def devices_add(request: Request,
                name: str = Form(...), ip: str = Form(...),
                port: int = Form(9100),
                manufacturer: str = Form(""),
                model: str = Form(""),
                profile: str = Form("generic"),
                paper_width_mm: int = Form(80),
                encoding: str = Form(config.DEFAULT_ENCODING),
                notes: str = Form(""),
                db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    form = dict(name=name, manufacturer=manufacturer, model=model,
                profile=profile, paper_width_mm=paper_width_mm,
                encoding=encoding, notes=notes)
    err = _create_printer_from_form(db, request, form, ip, port)
    if err:
        _flash(request, err, "err")
        return RedirectResponse("/devices", status_code=303)
    _flash(request, f"Impresora '{name}' registrada.")
    return RedirectResponse("/devices", status_code=303)


@router.post("/devices/{printer_id}/delete")
def devices_delete(printer_id: str, request: Request,
                   db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    p = db.get(models.Printer, printer_id)
    if p:
        pending = (db.query(models.Job)
                   .filter(models.Job.printer_id == p.id,
                           models.Job.status.in_(["pending", "processing"])).count())
        if pending:
            _flash(request, "Hay trabajos en cola para esa impresora.", "err")
        else:
            db.delete(p)
            models.audit(db, security.get_client_ip(request), "admin",
                         "printer.delete", {"id": printer_id})
            db.commit()
            _flash(request, "Impresora eliminada.")
    return RedirectResponse("/devices", status_code=303)


@router.post("/devices/{printer_id}/toggle")
def devices_toggle(printer_id: str, request: Request,
                   db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    p = db.get(models.Printer, printer_id)
    if p:
        p.active = 0 if p.active else 1
        db.commit()
    return RedirectResponse("/devices", status_code=303)


def _get_printer_or_404(db: Session, pid: str) -> models.Printer:
    p = db.get(models.Printer, pid)
    if p is None:
        raise HTTPException(404, "impresora no encontrada")
    return p


@router.get("/devices/{printer_id}")
def device_form(printer_id: str, request: Request,
                db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    p = _get_printer_or_404(db, printer_id)
    jobs = (db.query(models.Job).filter(models.Job.printer_id == p.id)
            .order_by(models.Job.created_at.desc()).limit(10).all())
    return _render(request, db, "device_form.html",
                   {"p": p, "jobs": jobs, "settings": p.settings or {}})


@router.post("/devices/{printer_id}")
def device_save(printer_id: str, request: Request,
                 name: str = Form(...), ip: str = Form(...),
                 port: int = Form(...), manufacturer: str = Form(""),
                 model: str = Form(""), profile: str = Form("generic"),
                 paper_width_mm: int = Form(80),
                 encoding: str = Form("auto"),
                 notes: str = Form(""), active: bool = Form(False),
                 cut: bool = Form(False), feed_before_cut: int = Form(3),
                 density: int = Form(-99), qr_size: int = Form(6),
                 db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    p = _get_printer_or_404(db, printer_id)
    allow_public = bool(models.get_setting(db, "allow_public_printer_ips", False))
    ok, why = security.printer_ip_allowed(ip, allow_public)
    if not ok:
        _flash(request, f"IP rechazada: {why}", "err")
        return RedirectResponse(f"/devices/{printer_id}", status_code=303)
    p.name, p.manufacturer, p.model, p.profile = name, manufacturer, model, profile
    p.ip, p.port = ip, port
    p.paper_width_mm = paper_width_mm
    p.columns = 32 if paper_width_mm == 58 else 48
    p.encoding = encoding
    p.notes = notes
    p.active = 1 if active else 0
    p.settings = {
        "cut": bool(cut), "feed_before_cut": feed_before_cut,
        "density": None if density == -99 else density,
        "logo": bool(p.settings or {}).get("logo", False),
        "qr_size": qr_size,
    }
    models.audit(db, security.get_client_ip(request), "admin",
                 "printer.update", {"id": printer_id})
    db.commit()
    _flash(request, f"'{name}' actualizada.")
    return RedirectResponse(f"/devices/{printer_id}", status_code=303)


# ------------------------------------------------------- buscar impresoras

@router.get("/discover")
def discover_form(request: Request, db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    ranges = models.get_setting(db, "discovery_ranges",
                                config.DEFAULT_DISCOVERY_RANGES)
    return _render(request, db, "discover.html",
                   {"ranges": ", ".join(ranges), "results": None})


@router.post("/discover")
async def discover_run(request: Request, cidr: str = Form(...),
                       ports: str = Form("9100"),
                       db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    try:
        port_list = [int(x) for x in ports.replace(",", " ").split()]
    except ValueError:
        port_list = [9100]
    try:
        results = await discovery.scan(cidr.strip(), port_list[:6])
        models.audit(db, security.get_client_ip(request), "admin",
                     "printers.discover", {"cidr": cidr, "found": len(results)})
        db.commit()
    except ValueError as exc:
        _flash(request, str(exc), "err")
        return RedirectResponse("/discover", status_code=303)
    return _render(request, db, "discover.html",
                   {"ranges": cidr, "results": results, "ports": ports})


# --------------------------------------------------------- prueba impresión

@router.get("/test_print")
def test_print_form(request: Request, db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    items = db.query(models.Printer).order_by(models.Printer.name).all()
    return _render(request, db, "test_print.html", {"printers": items})


@router.post("/test_print")
def test_print_run(request: Request,
                   printer_id: str = Form(...),
                   kind: str = Form("basico"),
                   db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    p = _get_printer_or_404(db, printer_id)
    company = models.get_setting(db, "company_name", "LBA")
    doc = rendering.test_ticket(p, kind, company,
                                models.get_setting(db, "logo_b64"))
    job, _created = queue_service.enqueue(db, p, doc, origin="test",
                                          meta={"kind": kind})
    db.commit()
    _flash(request, f"Ticket de prueba encolado (job {job.id[:8]}…). "
                    "Obsérvalo en la Cola.")
    return RedirectResponse("/queue", status_code=303)


# --------------------------------------------------------------------- cola

@router.get("/queue")
def queue_view(request: Request, status: str = "all",
               db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    return _queue_page(request, db, status)


@router.get("/queue/partials/rows")
def queue_rows(request: Request, status: str = "all",
               db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    return _queue_table(request, db, status)


def _queue_page(request: Request, db: Session, status: str):
    jobs = _queue_jobs(db, status)
    return _render(request, db, "queue.html",
                   {"jobs": jobs, "status_filter": status})


def _queue_table(request: Request, db: Session, status: str):
    jobs = _queue_jobs(db, status)
    return templates.TemplateResponse(
        request, "partials/queue_rows.html",
        {"request": request, "jobs": jobs, "status_filter": status})


def _queue_jobs(db: Session, status: str):
    q = db.query(models.Job)
    if status in ("pending", "processing", "sent", "failed", "cancelled"):
        q = q.filter(models.Job.status == status)
    return (q.order_by(models.Job.created_at.desc()).limit(50).all())


@router.post("/queue/{job_id}/retry")
def queue_retry(job_id: str, request: Request,
                db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    j = db.get(models.Job, job_id)
    if j and queue_service.retry(db, j):
        db.commit()
        _flash(request, "Trabajo reintentado.")
    else:
        _flash(request, "No se pudo reintentar.", "err")
    return RedirectResponse("/queue", status_code=303)


@router.post("/queue/{job_id}/cancel")
def queue_cancel(job_id: str, request: Request,
                 db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    j = db.get(models.Job, job_id)
    if j and queue_service.cancel(db, j):
        db.commit()
        _flash(request, "Trabajo cancelado.")
    else:
        _flash(request, "No se pudo cancelar.", "err")
    return RedirectResponse("/queue", status_code=303)


@router.post("/queue/{job_id}/reprint")
def queue_reprint(job_id: str, request: Request,
                  db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    j = db.get(models.Job, job_id)
    if j:
        new = queue_service.reprint(db, j)
        db.commit()
        _flash(request, f"Reimpresión encolada (job {new.id[:8]}…).")
    return RedirectResponse("/queue", status_code=303)


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Detalle completo de un trabajo (usado por Cola/Historial/Errores)."""
    if (r := _require(request)):
        return r
    j = db.get(models.Job, job_id)
    if j is None:
        raise HTTPException(404)
    events = (db.query(models.JobEvent)
              .filter(models.JobEvent.job_id == j.id)
              .order_by(models.JobEvent.ts).all())
    p = db.get(models.Printer, j.printer_id)
    return _render(request, db, "job_detail.html",
                   {"j": j, "p": p, "events": events,
                    "blob": bytes.fromhex(j.bytes_hex) if j.bytes_hex else b""})


# ---------------------------------------------------------------- historial

@router.get("/history")
def history(request: Request, db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    jobs = (db.query(models.Job)
            .filter(models.Job.status.in_(["sent", "failed", "cancelled"]))
            .order_by(models.Job.created_at.desc()).limit(100).all())
    return _render(request, db, "history.html", {"jobs": jobs})


@router.get("/errors")
def errors_view(request: Request, db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    jobs = (db.query(models.Job).filter(models.Job.status == "failed")
            .order_by(models.Job.updated_at.desc()).limit(100).all())
    printers = db.query(models.Printer).filter(models.Printer.status == "offline").all()
    return _render(request, db, "errors.html", {"jobs": jobs, "printers": printers})


# --------------------------------------------------------- configuración

@router.get("/settings")
def settings_form(request: Request, db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    return _render(request, db, "settings.html", {
        "company": models.get_setting(db, "company_name", "LBA"),
        "ranges": ", ".join(models.get_setting(db, "discovery_ranges",
                                               config.DEFAULT_DISCOVERY_RANGES)),
        "allowlist": ", ".join(models.get_setting(db, "ip_allowlist",
                                                  models.DEFAULT_ALLOWLIST)),
        "api_rate": models.get_setting(db, "api_rate_limit", config.API_RATE_LIMIT),
        "retention": models.get_setting(db, "retention_days",
                                        config.RETENTION_DAYS_DEFAULT),
        "allow_public": models.get_setting(db, "allow_public_printer_ips", False),
    })


@router.post("/settings")
def settings_save(request: Request,
                  company_name: str = Form(...),
                  discovery_ranges: str = Form(...),
                  ip_allowlist: str = Form(...),
                  api_limit: int = Form(120),
                  retention_days: int = Form(30),
                  allow_public: bool = Form(False),
                  db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    def _split(s: str) -> list[str]:
        return [x.strip() for x in s.replace(",", " ").split() if x.strip()]
    import ipaddress as _ipa
    for cidr in _split(discovery_ranges):
        try:
            _ipa.ip_network(cidr, strict=False)
        except ValueError:
            _flash(request, f"CIDR inválido: {cidr}", "err")
            return RedirectResponse("/settings", status_code=303)
    for cidr in _split(ip_allowlist):
        try:
            _ipa.ip_network(cidr, strict=False)
        except ValueError:
            _flash(request, f"CIDR de allowlist inválido: {cidr}", "err")
            return RedirectResponse("/settings", status_code=303)
    models.set_setting(db, "company_name", company_name[:100])
    models.set_setting(db, "discovery_ranges", _split(discovery_ranges))
    models.set_setting(db, "ip_allowlist", _split(ip_allowlist))
    models.set_setting(db, "api_rate_limit", {"limit": api_limit, "window_s": 60})
    models.set_setting(db, "retention_days", max(1, retention_days))
    models.set_setting(db, "allow_public_printer_ips", bool(allow_public))
    models.audit(db, security.get_client_ip(request), "admin",
                 "settings.update", {})
    db.commit()
    _flash(request, "Configuración guardada.")
    return RedirectResponse("/settings", status_code=303)


# ----------------------------------------------------------------- seguridad

@router.get("/security")
def security_view(request: Request, db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    tokens = models.get_setting(db, "api_tokens", [])
    audits = (db.query(models.AuditLog).order_by(models.AuditLog.ts.desc())
              .limit(50).all())
    return _render(request, db, "security.html",
                   {"tokens": tokens, "audits": audits,
                    "new_token": getattr(request, "new_token", None)})


@router.post("/security/tokens")
def token_create(request: Request, token_name: str = Form(""),
                 db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    value, record = security.new_api_token()
    record["name"] = token_name[:60] or "token"
    tokens = models.get_setting(db, "api_tokens", [])
    tokens.append(record)
    models.set_setting(db, "api_tokens", tokens)
    models.audit(db, security.get_client_ip(request), "admin",
                 "token.create", {"prefix": record["prefix"]})
    db.commit()
    request.new_token = value  # type: ignore[attr-defined]
    tokens = models.get_setting(db, "api_tokens", [])
    audits = (db.query(models.AuditLog).order_by(models.AuditLog.ts.desc())
              .limit(50).all())
    return _render(request, db, "security.html",
                   {"tokens": tokens, "audits": audits, "new_token": value},
                   status=201)


@router.post("/security/tokens/{prefix}/revoke")
def token_revoke(prefix: str, request: Request,
                 db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    tokens = models.get_setting(db, "api_tokens", [])
    kept = [t for t in tokens if t.get("prefix") != prefix]
    if len(kept) == len(tokens):
        _flash(request, "Token no encontrado.", "err")
    else:
        models.set_setting(db, "api_tokens", kept)
        models.audit(db, security.get_client_ip(request), "admin",
                     "token.revoke", {"prefix": prefix})
        db.commit()
        _flash(request, "Token revocado.")
    return RedirectResponse("/security", status_code=303)


@router.post("/security/password")
def password_change(request: Request,
                    current_password: str = Form(...),
                    new_password: str = Form(...),
                    db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    if not _password_ok(db, current_password):
        _flash(request, "Contraseña actual incorrecta.", "err")
        return RedirectResponse("/security", status_code=303)
    if len(new_password) < 8:
        _flash(request, "La nueva contraseña debe tener 8+ caracteres.", "err")
        return RedirectResponse("/security", status_code=303)
    models.set_setting(db, "admin", security.hash_password(new_password))
    models.audit(db, security.get_client_ip(request), "admin",
                 "password.change", {})
    db.commit()
    _flash(request, "Contraseña actualizada.")
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------------- backup

@router.get("/backup")
def backup(request: Request, db: Session = Depends(get_db)):
    if (r := _require(request)):
        return r
    out = config.DATA_DIR / f"lba-backup-{utcnow().strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(str(config.DB_PATH))
    dst = sqlite3.connect(str(out))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    models.audit(db, security.get_client_ip(request), "admin",
                 "backup.download", {"file": out.name})
    db.commit()
    return FileResponse(out, filename=out.name,
                         media_type="application/octet-stream")


@router.get("/healthz")
def healthz():
    """Healthcheck sin sesión (para systemd/monitor)."""
    return {"status": "ok"}
