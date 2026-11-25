#!/usr/bin/env bash
# ============================================================================
# LBA PRINT SYSTEM — verifica una instalación limpia desde el paquete tar.gz.
#
# Uso: bash deploy/scripts/verify_clean_install.sh <ruta/al/paquete.tar.gz>
#
# Comprueba, en un directorio temporal y SIN usar el checkout del repositorio:
#   1. el paquete contiene el árbol esperado y no incluye .venv/ni datos;
#   2. se crea un venv nuevo y se instalan solo las dependencias del paquete;
#   3. `pip check` no detecta requisitos rotos;
#   4. init_db() crea la BD y los archivos sensibles con modo 0600;
#   5. `import app.main` y el worker importan sin errores;
#   6. uvicorn sirve /api/v1/health con el esquema público mínimo;
#   7. `python -m app.worker --once` termina correctamente.
#
# Detecta regresiones de empaquetado (archivos que faltan, dependencias que no
# se declaran, imports que solo funcionan en el checkout de desarrollo).
# ============================================================================
set -euo pipefail

PACKAGE="${1:-}"
[[ -n "$PACKAGE" ]] || { echo "Uso: $0 <paquete.tar.gz>" >&2; exit 2; }
[[ -r "$PACKAGE" ]] || { echo "ERROR: paquete no legible: $PACKAGE" >&2; exit 2; }

PYTHON_BIN="${PYTHON_BIN:-python3}"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lba-clean-install-XXXXXX")"
chmod 0700 "$WORK_DIR"
PIDS=()

cleanup() {
    local rc=$?
    for pid in "${PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done
    for pid in "${PIDS[@]:-}"; do
        wait "$pid" 2>/dev/null || true
    done
    rm -rf -- "$WORK_DIR"
    exit "$rc"
}
trap cleanup EXIT INT TERM

fail() { echo "FALLO: $*" >&2; exit 1; }

echo "== Instalación limpia del paquete =="
echo "paquete: $PACKAGE"
echo "python:  $($PYTHON_BIN --version 2>&1)"
echo "workdir: $WORK_DIR"

tar -xzf "$PACKAGE" -C "$WORK_DIR"
SRC="$WORK_DIR/lba-print-server"
[[ -d "$SRC/server/app" ]] || fail "el paquete no contiene server/app"
[[ -f "$SRC/BUILD-INFO.txt" ]] || fail "falta BUILD-INFO.txt en el paquete"
[[ ! -e "$SRC/server/.venv" ]] || fail "el paquete no debe incluir server/.venv"
[[ ! -e "$SRC/server/data/lba.db" ]] || fail "el paquete no debe incluir la base de datos"
[[ ! -e "$SRC/.git" ]] || fail "el paquete no debe incluir .git"

echo "· creando venv aislado"
"$PYTHON_BIN" -m venv "$WORK_DIR/venv"
VENV_PY="$WORK_DIR/venv/bin/python"
"$VENV_PY" -m pip install --disable-pip-version-check --no-input -q \
    -r "$SRC/server/requirements.txt"
"$VENV_PY" -m pip check
"$VENV_PY" -m pip list --format=freeze > "$WORK_DIR/installed.txt"

export LBA_DATA_DIR="$WORK_DIR/data"
export LBA_ADMIN_PASSWORD="clean-install-test-pw"
export LBA_API_TOKEN="clean-install-test-token-0123456789"
export PYTHONPATH="$SRC/server"

echo "· inicializando la base de datos"
"$VENV_PY" -c 'from app.database.db import init_db; init_db()'

[[ -f "$LBA_DATA_DIR/lba.db" ]] || fail "init_db no creó lba.db"
[[ -f "$LBA_DATA_DIR/initial_credentials.txt" ]] || fail "faltan credenciales iniciales"
mode="$(stat -c '%a' "$LBA_DATA_DIR/initial_credentials.txt")"
[[ "$mode" == "600" ]] || fail "initial_credentials.txt tiene modo $mode (se esperaba 600)"
grep -q "clean-install-test-token" "$LBA_DATA_DIR/initial_credentials.txt" || \
    fail "las credenciales iniciales no reflejan el token del entorno"

echo "· importando la aplicación y el worker"
"$VENV_PY" - <<'PY'
import app.main
import app.worker.__main__  # noqa: F401
from app.database.db import get_engine
from sqlalchemy import inspect

assert app.main.app.title == "LBA Print Server"
tables = set(inspect(get_engine()).get_table_names())
required = {"printers", "jobs", "job_events", "settings", "audit_log"}
missing = required - tables
assert not missing, f"tablas ausentes: {sorted(missing)}"
print("   import OK; tablas:", ", ".join(sorted(required)))
PY
[[ -f "$LBA_DATA_DIR/secret_key" ]] || fail "la importación de la app no creó secret_key"
mode="$(stat -c '%a' "$LBA_DATA_DIR/secret_key")"
[[ "$mode" == "600" ]] || fail "secret_key tiene modo $mode (se esperaba 600)"

echo "· arrancando uvicorn"
PORT="$("$VENV_PY" - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
"$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
    --log-level warning > "$WORK_DIR/uvicorn.log" 2>&1 &
UVICORN_PID=$!
PIDS+=("$UVICORN_PID")

"$VENV_PY" - "$PORT" <<'PY'
import json
import sys
import time
import urllib.request

port = sys.argv[1]
url = f"http://127.0.0.1:{port}/api/v1/health"
deadline = time.time() + 45
last = None
while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            payload = json.load(response)
        break
    except Exception as exc:  # servidor aún arrancando
        last = exc
        time.sleep(0.5)
else:
    raise SystemExit(f"la API no respondió: {last}")
assert payload.get("status") == "ok", payload
assert payload.get("app") == "LBA Print Server", payload
assert set(payload) == {"status", "app", "version", "uptime_s"}, payload
assert "printers" not in payload and "queue" not in payload, payload
print("   /api/v1/health:", json.dumps(payload, sort_keys=True))
PY

kill "$UVICORN_PID" 2>/dev/null || true
wait "$UVICORN_PID" 2>/dev/null || true

echo "· ejecutando el worker en modo --once"
"$VENV_PY" -m app.worker --once > "$WORK_DIR/worker.log" 2>&1 || {
    cat "$WORK_DIR/worker.log" >&2
    fail "el worker no arrancó correctamente"
}

echo "· árbol del paquete verificado con pip check y arranque real"
echo "CLEAN INSTALL OK"
