#!/usr/bin/env bash
# ============================================================================
# LBA PRINT SYSTEM — recorrido funcional con simulador (sin hardware).
# Por defecto todo dato temporal se borra al salir. Para conservarlo de forma
# privada, ejecutar con LBA_DEMO_KEEP=1.
# Uso: bash deploy/scripts/demo_walkthrough.sh
# ============================================================================
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
cd server

find_free_port() {
  python3 - "$1" <<'PY'
import socket
import sys
start = int(sys.argv[1])
for port in range(start, start + 100):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        break
else:
    raise SystemExit("no hay un puerto local libre")
PY
}

DEMO_PORT="${LBA_DEMO_PORT:-$(find_free_port 18000)}"
SIM_PORT="${LBA_DEMO_SIM_PORT:-$(find_free_port 19000)}"
export LBA_PORT="$DEMO_PORT"
BASE="${BASE:-http://127.0.0.1:${DEMO_PORT}}"
BASE="${BASE%/}"
python3 - "$BASE" "${LBA_DEMO_ALLOW_REMOTE:-0}" <<'PY'
import ipaddress
import sys
from urllib.parse import urlsplit

base, allow_remote = sys.argv[1:]
try:
    parsed = urlsplit(base)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("BASE debe ser una URL HTTP(S) absoluta sin credenciales")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower().rstrip(".") == "localhost"
except ValueError as exc:
    print(f"BASE inválida: {exc}", file=sys.stderr)
    raise SystemExit(2)

if not loopback and allow_remote != "1":
    print(
        "Destino remoto rechazado: el walkthrough hace operaciones mutativas. "
        "Para asumir explícitamente ese riesgo, establezca LBA_DEMO_ALLOW_REMOTE=1.",
        file=sys.stderr,
    )
    raise SystemExit(2)
if not loopback:
    print("ADVERTENCIA: se ejecutará el walkthrough contra un destino remoto.", file=sys.stderr)
PY

RUN_DIR="$(mktemp -d /tmp/lba-demo-XXXXXX)"
chmod 0700 "$RUN_DIR"
export LBA_DATA_DIR="$RUN_DIR/data"
export LBA_ADMIN_PASSWORD="${LBA_ADMIN_PASSWORD:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')}"
export LBA_API_TOKEN="${LBA_API_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
TOKEN="$LBA_API_TOKEN"
COOKIE_FILE="$RUN_DIR/session.cookies"
SIM_LOG="$RUN_DIR/simulator.log"
API_LOG="$RUN_DIR/api.log"
WORKER_LOG="$RUN_DIR/worker.log"
PIDS=()
cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
    for p in "${PIDS[@]:-}"; do wait "$p" 2>/dev/null || true; done
    if [[ "${LBA_DEMO_KEEP:-0}" == "1" ]]; then
        echo "Datos/logs privados conservados en $RUN_DIR (modo 0700; cookies/token sensibles)."
    else
        rm -rf -- "$RUN_DIR"
        echo "Datos, cookies y logs temporales eliminados."
    fi
    return "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '· directorio temporal privado: %s\n' "$RUN_DIR"
python -m app.drivers.simulator --port "$SIM_PORT" --print >"$SIM_LOG" 2>&1 & PIDS+=($!)
python -m uvicorn app.main:app --host 127.0.0.1 --port "$DEMO_PORT" --log-level warning >"$API_LOG" 2>&1 & PIDS+=($!)
python -m app.worker >"$WORKER_LOG" 2>&1 & PIDS+=($!)

echo "· esperando a la API…"
READY=0
for _ in $(seq 1 40); do
  if curl -sf "$BASE/api/v1/health" >/dev/null; then READY=1; break; fi
  sleep 0.5
done
if (( READY != 1 )); then
  echo "La API no quedó lista; logs: $API_LOG" >&2
  exit 1
fi

echo; echo "== 1) Salud del servidor =="
curl -s "$BASE/api/v1/health"; echo

echo; echo "== 2) Registrar impresora (simulador en 127.0.0.1:$SIM_PORT) =="
PRINTERS=$(curl -s -X POST "$BASE/api/v1/printers" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"name\":\"Cocina (demo)\",\"ip\":\"127.0.0.1\",\"port\":$SIM_PORT,\"profile\":\"simulator\",\"paper_width_mm\":80,\"encoding\":\"CP850\",\"manufacturer\":\"LBA\",\"model\":\"Simulator\"}")
echo "$PRINTERS" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("id:", d["id"], "|", d["name"], "|", d["ip"]+":"+str(d["port"]), "|", d["protocol"])'
PR_ID=$(echo "$PRINTERS" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo; echo "== 3) Descubrimiento en loopback únicamente (127.0.0.0/29) =="
curl -s -X POST "$BASE/api/v1/printers/discover" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"cidr\":\"127.0.0.0/29\",\"ports\":[$SIM_PORT]}"; echo

echo; echo "== 4) Ticket de prueba 'caracteres' (ñ áéíóú ¿¡) =="
JOB=$(curl -s -X POST "$BASE/api/v1/printers/$PR_ID/test" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"kind":"caracteres"}')
JOB_ID=$(echo "$JOB" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "job: $JOB_ID — esperando al worker…"
sleep 2

echo; echo "== 5) Estado del trabajo (sent = enviado por TCP, NO 'impreso') =="
curl -s "$BASE/api/v1/jobs/$JOB_ID" -H "Authorization: Bearer $TOKEN" | \
  python3 -c 'import sys,json; j=json.load(sys.stdin)
print("estado:", j["status"], "| intentos:", j["attempts"], "| bytes:", j["bytes_len"])
print("---- vista previa (reconstrucción de lo enviado) ----")
print(j.get("preview") or "(sin vista previa)")'

echo; echo "== 6) Idempotencia: misma clave, dos envíos → 409 sin duplicar =="
DOC='{"type":"ticket","blocks":[{"type":"text","value":"COMANDA MESA 4 — ñ"}]}'
J1=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/v1/jobs" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"printer_id\":\"$PR_ID\",\"origin\":\"odoo\",\"idempotency_key\":\"odoo:demo:1\",\"document\":$DOC}")
J2=$(curl -s -X POST "$BASE/api/v1/jobs" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"printer_id\":\"$PR_ID\",\"origin\":\"odoo\",\"idempotency_key\":\"odoo:demo:1\",\"document\":$DOC}")
echo "1º envío: HTTP $J1 | 2º envío: HTTP $(echo "$J2" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status_code") or 409)') → $(echo "$J2" | head -c 160)"

echo; echo "== 7) Panel web: login y secciones =="
curl -s -c "$COOKIE_FILE" -o /dev/null -w 'login: HTTP %{http_code}\n' \
  -X POST "$BASE/login" --data "password=$LBA_ADMIN_PASSWORD"
for seccion in / /devices /discover /test_print /queue /history /errors /settings /security; do
  code=$(curl -s -b "$COOKIE_FILE" -o /dev/null -w '%{http_code}' "$BASE$seccion")
  echo "  $seccion → $code"
done
curl -s -b "$COOKIE_FILE" "$BASE/jobs/$JOB_ID" | grep -q "Cocina (demo)" && \
  echo "  detalle del trabajo en panel: OK (impresora visible)"
tail -6 "$SIM_LOG" | sed 's/^/  [simulador] /'
echo; echo "== FIN: procesos detenidos al salir; logs privados en $RUN_DIR hasta limpieza =="
