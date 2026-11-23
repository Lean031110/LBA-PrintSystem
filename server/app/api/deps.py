"""Dependencias de autenticación de la API y del panel."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.core import config, security
from app.database.db import get_db
from app.models import models


def check_ip(request: Request, db) -> str:
    ip = security.get_client_ip(request)
    allowlist = models.get_setting(db, "ip_allowlist",
                                  models.DEFAULT_ALLOWLIST)
    ok, msg = security.client_ip_allowed(ip, allowlist)
    if not ok:
        models.audit(db, ip, "api", "ip.denied", {"reason": msg, "path": request.url.path})
        db.commit()
        raise HTTPException(403, f"IP no autorizada: {msg}")
    return ip


def check_token(request: Request, db) -> str:
    token = security.extract_token(request)
    if not token:
        raise HTTPException(401, "Token ausente (Authorization: Bearer … o X-API-Token)")
    tokens = models.get_setting(db, "api_tokens", [])
    if not any(t.get("hash") == security.token_hash(token) for t in tokens):
        ip = security.get_client_ip(request)
        models.audit(db, ip, "api", "token.invalid",
                    {"path": request.url.path})
        # La excepción HTTP aborta la transacción de la petición al cerrar
        # get_db; confirma solo el evento saneado, nunca el token recibido.
        db.commit()
        raise HTTPException(401, "Token inválido o revocado")
    return security.token_hash(token)[:12]


def check_rate(request: Request, db, scope: str = "api") -> None:
    ip = security.get_client_ip(request)
    if scope == "login":
        rl = models.get_setting(db, "login_rate_limit", config.LOGIN_RATE_LIMIT)
    else:
        rl = models.get_setting(db, "api_rate_limit", config.API_RATE_LIMIT)
    ok, _ = security.rate_limiter.allow(
        f"{scope}:{ip}", int(rl.get("limit", 120)), int(rl.get("window_s", 60)))
    if not ok:
        raise HTTPException(429, "Límite de peticiones alcanzado (rate limit)")


def api_auth(request: Request, db=Depends(get_db)) -> dict:
    """Autenticación completa de /api/v1: IP allowlist + token + rate limit."""
    ip = check_ip(request, db)
    check_token(request, db)
    check_rate(request, db, "api")
    return {"ip": ip}
