"""Motor SQLite + sesión SQLAlchemy. WAL + busy_timeout para API y worker."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(str(config.DB_PATH)), exist_ok=True)


def get_engine():
    global _engine
    if _engine is None:
        _ensure_dir()
        _engine = create_engine(
            f"sqlite:///{config.DB_PATH}",
            connect_args={"check_same_thread": False, "timeout": 15},
            pool_pre_ping=True,
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _):  # pragma: no cover
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.close()

    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False,
                                     expire_on_commit=False)
    return _SessionLocal


def get_db():
    """Dependencia FastAPI: una sesión por petición."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Crea tablas e inserta valores por defecto (idempotente)."""
    from app.models import models  # noqa: F401  (registra los ORM)
    Base.metadata.create_all(bind=get_engine())
    # create_all no altera tablas existentes: esta columna aditiva permite que
    # bases previas adopten el lease sin borrar ni reconstruir la cola.
    columns = {c["name"] for c in inspect(get_engine()).get_columns("jobs")}
    if "claim_expires_at" not in columns:
        try:
            with get_engine().begin() as conn:
                conn.execute(text(
                    "ALTER TABLE jobs ADD COLUMN claim_expires_at DATETIME"))
        except OperationalError:
            # API y worker pueden arrancar juntos; acepta solo si el otro
            # proceso ya aplicó exactamente esta migración aditiva.
            columns = {c["name"] for c in inspect(get_engine()).get_columns("jobs")}
            if "claim_expires_at" not in columns:
                raise
    # La API y el worker pueden inicializar a la vez una BD nueva (contenedor
    # Docker con LBA_ROLE=all, dos servicios recién instalados). El primer
    # proceso que inserta los ajustes gana; el otro debe reintentar en lugar
    # de abortar con UNIQUE(settings.key) o una escritura bloqueada.
    last_error: Exception | None = None
    for attempt in range(3):
        with get_sessionmaker()() as db:
            try:
                models.ensure_default_settings(db)
                db.commit()
                return
            except (IntegrityError, OperationalError) as exc:
                db.rollback()
                last_error = exc
        time.sleep(0.1 * (attempt + 1))
    # Si otro proceso ya sembró los ajustes, la inicialización es correcta.
    with get_sessionmaker()() as db:
        if (models.get_setting(db, "admin") is not None
                and models.get_setting(db, "api_tokens") is not None):
            return
    assert last_error is not None
    raise last_error
