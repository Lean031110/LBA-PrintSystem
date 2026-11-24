"""Modelos ORM (SQLAlchemy 2.x, estilo declarativo)."""
from __future__ import annotations

import os
import secrets as pysecrets
import uuid
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text

from app.database.db import Base, utcnow, get_sessionmaker
from app.core import config
from app.core.security import hash_password, new_api_token


def _uuid() -> str:
    return str(uuid.uuid4())


class Printer(Base):
    __tablename__ = "printers"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(100), nullable=False)
    manufacturer = Column(String(60), default="", nullable=False)
    model = Column(String(60), default="", nullable=False)
    profile = Column(String(20), default="generic", nullable=False)  # generic|simulator
    connection_type = Column(String(20), default="network", nullable=False)
    protocol = Column(String(30), default="escpos_raw_tcp", nullable=False)
    ip = Column(String(60), nullable=False)
    port = Column(Integer, default=9100, nullable=False)
    paper_width_mm = Column(Integer, default=80, nullable=False)   # 58 | 80
    columns = Column(Integer, default=48, nullable=False)           # 32 | 48
    encoding = Column(String(20), default=config.DEFAULT_ENCODING, nullable=False)
    status = Column(String(20), default="unknown", nullable=False)  # unknown|online|offline|deleted
    last_seen_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="", nullable=False)
    notes = Column(Text, default="", nullable=False)
    active = Column(Integer, default=1, nullable=False)             # SQLite bool
    settings = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=_uuid)
    idempotency_key = Column(String(200), unique=True, nullable=True, index=True)
    printer_id = Column(String(36), ForeignKey("printers.id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)             # documento estructurado completo
    origin = Column(String(20), default="api", nullable=False)  # api|odoo|panel|test|reprint
    meta = Column(JSON, default=dict, nullable=False)
    status = Column(String(20), default="pending", nullable=False, index=True)
    # pending | processing | sent | failed | cancelled
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=config.MAX_ATTEMPTS_DEFAULT, nullable=False)
    next_attempt_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    # Lease temporal del claim del worker; NULL fuera de processing.
    claim_expires_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="", nullable=False)
    bytes_hex = Column(Text, nullable=True)            # bytes ESC/POS enviados (auditoría)
    bytes_len = Column(Integer, default=0, nullable=False)
    preview_text = Column(Text, nullable=True)         # reconstrucción textual
    priority = Column(Integer, default=100, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    ts = Column(DateTime, default=utcnow, nullable=False)
    from_status = Column(String(20), default="", nullable=False)
    to_status = Column(String(20), nullable=False)
    detail = Column(Text, default="", nullable=False)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(60), primary_key=True)
    value = Column(JSON, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=utcnow, nullable=False, index=True)
    ip = Column(String(60), default="", nullable=False)
    subject = Column(String(20), default="", nullable=False)  # admin|api|worker
    action = Column(String(60), nullable=False)
    detail = Column(JSON, default=dict, nullable=False)


# ------------------------------------------------------------ helpers settings

DEFAULT_ALLOWLIST = ["127.0.0.1/32", "::1/128", "10.0.0.0/8",
                     "172.16.0.0/12", "192.168.0.0/16"]


def get_setting(db, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    return row.value if row is not None else default


def set_setting(db, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def audit(db, ip: str, subject: str, action: str, detail: Optional[dict] = None) -> None:
    db.add(AuditLog(ip=ip, subject=subject, action=action, detail=detail or {}))


def archive_printer(db, printer: Printer) -> None:
    """Desactiva y anonimiza el destino, reteniendo la fila referenciada por jobs."""
    printer.status = "deleted"
    printer.active = 0
    printer.ip = ""
    printer.last_error = ""
    printer.notes = ""
    printer.settings = {}


def ensure_default_settings(db) -> dict:
    """Inicializa ajustes y credenciales. Devuelve credenciales nuevas (1ª vez)."""
    created: dict = {}
    if get_setting(db, "ip_allowlist") is None:
        set_setting(db, "ip_allowlist", DEFAULT_ALLOWLIST)
    if get_setting(db, "discovery_ranges") is None:
        set_setting(db, "discovery_ranges", config.DEFAULT_DISCOVERY_RANGES)
    if get_setting(db, "api_rate_limit") is None:
        set_setting(db, "api_rate_limit", config.API_RATE_LIMIT)
    if get_setting(db, "retention_days") is None:
        set_setting(db, "retention_days", config.RETENTION_DAYS_DEFAULT)
    if get_setting(db, "company_name") is None:
        set_setting(db, "company_name", "LBA DEMO")
    if get_setting(db, "logo_b64") is None:
        set_setting(db, "logo_b64", None)
    if get_setting(db, "allow_public_printer_ips") is None:
        set_setting(db, "allow_public_printer_ips", False)

    if get_setting(db, "admin") is None:
        env_pw = os.environ.get("LBA_ADMIN_PASSWORD")
        password = env_pw if env_pw else (pysecrets.token_urlsafe(12))
        set_setting(db, "admin", hash_password(password))
        created["admin_password"] = password
        created["password_generated"] = not bool(env_pw)

    if get_setting(db, "api_tokens") is None:
        env_tok = os.environ.get("LBA_API_TOKEN")
        if env_tok:
            from app.core.security import token_hash
            tokens = [{"name": "inicial(env)", "prefix": env_tok[:12],
                       "hash": token_hash(env_tok),
                       "created": utcnow().isoformat(timespec="seconds") + "Z"}]
            created["api_token"] = env_tok
        else:
            value, record = new_api_token()
            tokens = [record]
            created["api_token"] = value
        set_setting(db, "api_tokens", tokens)

    # Limpieza inicial opcional (no ejecutada salvo tests)
    if created:
        try:
            cred_file = config.DATA_DIR / "initial_credentials.txt"
            cred_file.write_text(
                "LBA PRINT SYSTEM — credenciales iniciales (borra este archivo)\n"
                f"fecha: {utcnow().isoformat(timespec='seconds')}Z\n"
                f"panel: http://{config.HOST}:{config.PORT}/ (usuario: admin)\n"
                f"contraseña: {created.get('admin_password', '')}\n"
                f"token API: {created.get('api_token', '')}\n",
                encoding="utf-8",
            )
            cred_file.chmod(0o600)
        except OSError:
            pass
    return created


def purge_expired(db, retention_days: int) -> int:
    """Elimina trabajos terminados más antiguos que la retención."""
    cutoff = utcnow() - timedelta(days=retention_days)
    done = (db.query(Job)
              .filter(Job.status.in_(["sent", "failed", "cancelled"]))
              .filter(Job.created_at < cutoff).all())
    n = len(done)
    for j in done:
        db.query(JobEvent).filter(JobEvent.job_id == j.id).delete()
        db.delete(j)
    return n


def recover_orphan_processing(db) -> int:
    """Reencola solo claims vencidos; entrega at-least-once, no exactly-once.

    Si el worker cayó después de que el dispositivo recibiera el ticket y antes
    de persistir `sent`, no puede saberse si hubo impresión física; la
    recuperación puede duplicarla. Las conexiones de impresión están acotadas
    por timeout y el claim tiene un lease más largo que esa operación.
    """
    now = utcnow()
    orphans = (db.query(Job).filter(Job.status == "processing")
               .filter((Job.claim_expires_at.is_(None)) |
                       (Job.claim_expires_at <= now)).all())
    for j in orphans:
        j.status = "pending"
        j.next_attempt_at = now
        j.claim_expires_at = None
        db.add(JobEvent(job_id=j.id, from_status="processing", to_status="pending",
                        detail="claim vencido recuperado; entrega at-least-once"))
    return len(orphans)
