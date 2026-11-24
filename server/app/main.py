"""LBA Print Server — aplicación FastAPI (API + panel)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import routes as api_routes
from app.core import config
from app.database.db import init_db


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=config.APP_NAME,
        version=config.APP_VERSION,
        description=("Servidor de impresión térmica ESC/POS para Odoo 19 "
                     "(red local, sin nube)."),
        docs_url="/docs", redoc_url="/redoc",
        lifespan=_lifespan,
    )
    app.include_router(api_routes.router)

    from app.dashboard import routes_panel
    app.include_router(routes_panel.router)

    static = Path(__file__).resolve().parent / "dashboard" / "static"
    app.mount("/static", StaticFiles(directory=str(static)), name="static")
    return app


app = create_app()
