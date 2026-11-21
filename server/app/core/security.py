"""Seguridad: contraseñas PBKDF2, tokens, allowlist IP, rate limit, sesiones firmadas.

Nada de esto se persiste en el código fuente: los secretos viven en la BD
(hash) y en LBA_DATA_DIR/secret_key (firma de cookies).
"""
from __future__ import annotations

import hashlib
import ipaddress
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Iterable, Optional

from fastapi import Request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.core import config

# ---------------------------------------------------------------- contraseñas

PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> dict:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return {"algo": "pbkdf2_sha256", "iter": PBKDF2_ITERATIONS,
            "salt": salt.hex(), "hash": dk.hex()}


def verify_password(password: str, stored: dict) -> bool:
    try:
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(stored["salt"]), stored["iter"]
        )
        return secrets.compare_digest(dk.hex(), stored["hash"])
    except Exception:
        return False


# ------------------------------------------------------------------- tokens

def new_api_token() -> tuple[str, dict]:
    """Devuelve (valor_completo_para_mostrar_UNA_VEZ, registro_para_bd_con_hash)."""
    value = "lba_" + secrets.token_urlsafe(32)
    record = {
        "name": "",
        "prefix": value[:12],
        "hash": hashlib.sha256(value.encode()).hexdigest(),
        "created": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    return value, record


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-API-Token")


# -------------------------------------------------------------------- redes

def _nets(specs: Iterable[str]) -> list:
    nets = []
    for s in specs:
        try:
            nets.append(ipaddress.ip_network(s, strict=False))
        except ValueError:
            continue
    return nets


_ALLOWED_NETS = _nets(config.PRINTER_ALLOWED_NETS)
_BLOCKED_NETS = _nets(config.PRINTER_BLOCKED_NETS)


def printer_ip_allowed(ip_str: str, allow_public: bool = False) -> tuple[bool, str]:
    """Valida que la IP de una impresora/destino sea alcanzable en LAN privada.

    Protege frente a SSRF: bloquea metadatos de nube, CGNAT, rangos de test y
    IPs públicas (salvo 'allow_public_printer_ips' activado explícitamente).
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False, "IP no válida"
    if any(ip in net for net in _BLOCKED_NETS):
        return False, "Rango bloqueado por política (SSRF)"
    if any(ip in net for net in _ALLOWED_NETS):
        return True, "ok"
    if ip.is_loopback:
        return True, "ok"
    if allow_public:
        return True, "ok (públicas permitidas explícitamente)"
    return False, ("IP pública no permitida (solo LAN privada; "
                   "habilita allow_public_printer_ips si es intencional)")


def client_ip_allowed(ip_str: str, allowlist: Iterable[str]) -> tuple[bool, str]:
    if not allowlist:  # vacío = denegar todo
        return False, "Allowlist vacía"
    nets = _nets(allowlist)
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False, "IP de cliente no válida"
    if any(ip in net for net in nets):
        return True, "ok"
    return False, "IP de cliente fuera de la allowlist"


def get_client_ip(request: Request) -> str:
    # Confiamos solo en la IP del socket (no en X-Forwarded-For forjable).
    if request.client and request.client.host:
        return request.client.host
    return "0.0.0.0"


# --------------------------------------------------------------- rate limit

class RateLimiter:
    """Ventana deslizante en memoria (suficiente para servicio de LAN)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_s: int) -> tuple[bool, int]:
        now = time.monotonic()
        dq = self._hits[key]
        while dq and now - dq[0] > window_s:
            dq.popleft()
        if len(dq) >= limit:
            return False, limit - len(dq)
        dq.append(now)
        return True, limit - len(dq)


rate_limiter = RateLimiter()


# ------------------------------------------------------------------ sesiones

class SessionSigner:
    def __init__(self, secret: str) -> None:
        self._s = URLSafeTimedSerializer(secret, salt="lba-panel-session")

    def sign(self, data: str) -> str:
        return self._s.dumps({"sub": data})

    def verify(self, token: str, max_age_s: int) -> Optional[str]:
        try:
            data = self._s.loads(token, max_age=max_age_s)
            return data.get("sub")
        except (BadSignature, SignatureExpired):
            return None
