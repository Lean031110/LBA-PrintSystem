"""Motor SQLite + sesión SQLAlchemy. WAL + busy_timeout para API y worker."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
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
    with get_sessionmaker()() as db:
        models.ensure_default_settings(db)
        db.commit()
