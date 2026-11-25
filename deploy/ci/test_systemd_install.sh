#!/usr/bin/env bash
# ============================================================================
# Validación de install.sh con systemd REAL.
#
# Se ejecuta DENTRO de un contenedor privilegiado con systemd como PID 1
# (deploy/ci/systemd/Dockerfile), con el repositorio montado en /src:ro.
# Comprueba instalación, unidades, credenciales, impresión con la impresora
# virtual del sistema, reinicio del servicio y reinstalación idempotente.
# ============================================================================
set -euo pipefail

SRC="${LBA_CI_SRC:-/src}"
WORK=/tmp/lba-install-src
PORT=8000
SIM_PORT=9910
API="http://127.0.0.1:${PORT}"
CREDENTIALS=/var/lib/lba/initial_credentials.txt

log() { printf '\n== %s ==\n' "$*"; }
fail() { printf 'FALLO: %s\n' "$*" >&2; exit 1; }

wait_http() {
    local url="$1" label="$2" deadline=$((SECONDS + 90))
    until curl -fsS "$url" >/dev/null 2>&1; do
        (( SECONDS < deadline )) || fail "$label no respondió en 90 s"
        sleep 1
    done
}

log "Preparando copia de trabajo del repositorio"
rm -rf "$WORK"
cp -a "$SRC" "$WORK"
rm -rf "$WORK/server/.venv" "$WORK/server/data" "$WORK/.git"
export LBA_DOWNLOAD_RETRIES=4 LBA_RETRY_BASE_SECONDS=2 LBA_RETRY_MAX_SECONDS=8
export LBA_PIP_RETRIES=5

log "Instalación real (install.sh)"
bash "$WORK/deploy/scripts/install.sh" "$WORK"

log "Unidades systemd habilitadas y activas"
for unit in lba-print-api.service lba-print-worker.service; do
    systemctl is-enabled "$unit" >/dev/null || fail "$unit no está habilitada"
    systemctl is-active "$unit" >/dev/null || fail "$unit no está activa"
done
[[ -f /etc/systemd/system/lba-print-simulator.service ]] || \
    fail "la unidad del simulador no quedó instalada"
if systemctl is-active lba-print-simulator.service >/dev/null 2>&1; then
    fail "el simulador no debe arrancar por defecto en producción"
fi

log "Archivos, permisos y credenciales"
[[ -f /opt/lba/server/app/main.py ]] || fail "código no instalado en /opt/lba"
[[ "$(stat -c '%a' /etc/lba-print/lba-print.env)" == "640" ]] || \
    fail "modo incorrecto en lba-print.env"
[[ "$(stat -c '%a' "$CREDENTIALS")" == "600" ]] || \
    fail "modo incorrecto en initial_credentials.txt"
grep -q '^LBA_PORT=8000$' /etc/lba-print/lba-print.env || fail "LBA_PORT ausente"
# Regresión: con umask restrictivo el venv quedaba en 0700 root y el usuario de
# servicio no podía ejecutar el intérprete (env: Permission denied).
sudo -u lba test -x /opt/lba/server/.venv/bin/python || \
    fail "el usuario lba no puede ejecutar el python del venv (permisos)"
sudo -u lba env PYTHONPATH=/opt/lba/server /opt/lba/server/.venv/bin/python \
    -c 'import app.main' >/dev/null 2>&1 || \
    fail "el usuario lba no puede importar app.main con el venv instalado"

log "Healthcheck público mínimo"
HEALTH="$(curl -fsS "$API/api/v1/health")"
python3 - "$HEALTH" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
assert payload.get("status") == "ok", payload
assert set(payload) == {"status", "app", "version", "uptime_s"}, payload
print("health:", json.dumps(payload, sort_keys=True))
PY

TOKEN="$(awk -F': ' '/token API/ {print $2}' "$CREDENTIALS")"
[[ -n "$TOKEN" ]] || fail "no se pudo leer el token API de las credenciales"

log "Impresora virtual (simulador) + impresión real por la cola"
systemctl enable --now lba-print-simulator.service
wait_port_timeout=$((SECONDS + 30))
until python3 - "$SIM_PORT" <<'PY'
import socket, sys
with socket.socket() as sock:
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
do
    (( SECONDS < wait_port_timeout )) || fail "el simulador no escuchó en $SIM_PORT"
    sleep 1
done

PRINTER_JSON="$(curl -fsS -X POST "$API/api/v1/printers" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"name\":\"Cocina CI\",\"ip\":\"127.0.0.1\",\"port\":$SIM_PORT,\"profile\":\"simulator\",\"paper_width_mm\":80,\"encoding\":\"CP850\"}")"
PRINTER_ID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$PRINTER_JSON")"

JOB_JSON="$(curl -fsS -X POST "$API/api/v1/printers/$PRINTER_ID/test" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"kind":"caracteres"}')"
JOB_ID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$JOB_JSON")"

STATUS=""
for _ in $(seq 1 60); do
    STATUS="$(curl -fsS "$API/api/v1/jobs/$JOB_ID" -H "Authorization: Bearer $TOKEN" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
    [[ "$STATUS" == "sent" ]] && break
    [[ "$STATUS" == "failed" ]] && fail "el trabajo terminó en failed"
    sleep 1
done
[[ "$STATUS" == "sent" ]] || fail "el trabajo no se transmitió (estado $STATUS)"

for _ in $(seq 1 30); do
    journalctl -u lba-print-simulator.service --no-pager --since "-5 min" \
        2>/dev/null | grep -q "ticket recibido" && break
    sleep 1
done
journalctl -u lba-print-simulator.service --no-pager --since "-5 min" | \
    grep -q "ticket recibido" || fail "la impresora virtual no registró el ticket"

log "Persistencia tras reiniciar la API"
BEFORE="$(curl -fsS "$API/api/v1/stats" -H "Authorization: Bearer $TOKEN")"
systemctl restart lba-print-api.service
wait_http "$API/api/v1/health" "API tras restart"
AFTER="$(curl -fsS "$API/api/v1/stats" -H "Authorization: Bearer $TOKEN")"
python3 - "$BEFORE" "$AFTER" <<'PY'
import json, sys
before, after = (json.loads(value) for value in sys.argv[1:])
assert after["queue"]["sent"] >= before["queue"]["sent"] >= 1, (before, after)
print("cola tras restart:", after["queue"])
PY

log "Reinstalación idempotente sobre la instalación existente"
CRED_HASH="$(sha256sum "$CREDENTIALS" | cut -d' ' -f1)"
bash "$WORK/deploy/scripts/install.sh" "$WORK"
[[ "$(sha256sum "$CREDENTIALS" | cut -d' ' -f1)" == "$CRED_HASH" ]] || \
    fail "la reinstalación regeneró las credenciales"
wait_http "$API/api/v1/health" "API tras reinstalar"
systemctl is-active lba-print-worker.service >/dev/null || \
    fail "el worker no quedó activo tras reinstalar"

log "SYSTEMD INSTALL OK"
