"""Configuración central del LBA Print Server.

Todas las rutas y secretos se resuelven por variables de entorno (ver deploy/).
No se almacena ningún secreto en el código fuente.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

# --- Identidad -------------------------------------------------------------
APP_NAME = "LBA Print Server"
APP_VERSION = "1.0.0"

# --- Rutas -----------------------------------------------------------------
SERVER_DIR = Path(__file__).resolve().parent.parent.parent  # server/
DATA_DIR = Path(os.environ.get("LBA_DATA_DIR", str(SERVER_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("LBA_DB_PATH", str(DATA_DIR / "lba.db")))
SECRET_PATH = DATA_DIR / "secret_key"

# --- Red -------------------------------------------------------------------
HOST = os.environ.get("LBA_HOST", "0.0.0.0")
PORT = int(os.environ.get("LBA_PORT", "8000"))

# Rangos donde PUEDEN vivir impresoras (anti-SSRF: LAN privada + loopback).
PRINTER_ALLOWED_NETS = [
    "127.0.0.0/8", "::1/128",
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
]
# Rangos SIEMPRE bloqueados (metadatos de nube, CGNAT, etc.).
PRINTER_BLOCKED_NETS = [
    "169.254.0.0/16", "100.64.0.0/10", "0.0.0.0/8", "192.0.2.0/24",
    "198.51.100.0/24", "203.0.113.0/24",
]
# Rangos de discovery por defecto (editables en el panel). Loopback permite
# probar el simulador local sin abrir el escaneo a ninguna red externa.
DEFAULT_DISCOVERY_RANGES = ["127.0.0.0/8", "192.168.1.0/24"]

# --- Codificaciones soportadas (ES) -----------------------------------------
# Código ESC/POS "ESC t n" por codepage (tabla Epson estándar seguida por clones).
ENCODING_TABLE = {
    "CP437": 0,
    "CP850": 2,
    "CP852": 18,
    "Windows-1252": 16,
}
DEFAULT_ENCODING = "CP850"

# --- Cola / worker ----------------------------------------------------------
MAX_ATTEMPTS_DEFAULT = 5
BACKOFF_BASE_S = 5          # 5s, 10s, 20s, 40s, 80s ...
BACKOFF_MAX_S = 300
SOCKET_TIMEOUT_S = 5.0
WORKER_POLL_S = 0.5
WORKER_HEALTHCHECK_S = 60.0  # ping TCP periódico de impresoras activas

# --- Rate limits -------------------------------------------------------------
API_RATE_LIMIT = {"limit": 120, "window_s": 60}
LOGIN_RATE_LIMIT = {"limit": 8, "window_s": 60}

# --- Sesión del panel ---------------------------------------------------------
SESSION_TTL_S = 8 * 3600
COOKIE_NAME = "lba_session"

# --- Límites de payload (validación Pydantic + servidor) ----------------------
MAX_BLOCKS = 200
MAX_TEXT_CHARS = 4000
MAX_QR_CHARS = 1000
MAX_IMAGE_B64_KB = 300

# --- Retención ---------------------------------------------------------------
RETENTION_DAYS_DEFAULT = 30


def get_or_create_secret() -> str:
    """Llave para firmar cookies de sesión (nunca se versiona)."""
    if SECRET_PATH.exists():
        return SECRET_PATH.read_text().strip()
    key = secrets.token_hex(32)
    SECRET_PATH.write_text(key)
    SECRET_PATH.chmod(0o600)
    return key
