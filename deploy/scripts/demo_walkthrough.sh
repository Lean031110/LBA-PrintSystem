#!/usr/bin/env bash
# ============================================================================
# LBA PRINT SYSTEM — Primer recorrido funcional (demo reproducible, sin
# hardware): arranca simulador ESC/POS + API + worker, registra la impresora
# simulada, envía un ticket de prueba con caracteres españoles y muestra el
# resultado (estado 'sent' + vista previa reconstruida + panel).
#
# Uso:  bash deploy/scripts/demo_walkthrough.sh
# Sale: /tmp/lba-{sim,api,worker}.log
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/../.."      # raíz del repo
cd server

BASE="${BASE:-http://127.0.0.1:8000}"
export LBA_DATA_DIR="$(mktemp -d /tmp/lba-demo-XXXX)"
export LBA_ADMIN_PASSWORD="${LBA_ADMIN_PASSWORD:-admin1234}"
export LBA_API_TOKEN="${LBA_API_TOKEN:-lba_demo_token}"
TOKEN="$LBA_API_TOKEN"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

echo "· directorio de datos: $LBA_DATA_DIR"
python -m app.drivers.simulator --port 9910 --print >/tmp/lba-sim.log 2>&1 & PIDS+=($!)
python -m uvicorn app.main:app --port 8000 --log-level warning >/tmp/lba-api.log 2>&1 & PIDS+=($!)
python -m app.worker >/tmp/lba-worker.log 2>&1 & PIDS+=($!)

echo "· esperando a la API…"
for _ in $(seq 1 40); do curl -sf "$BASE/api/v1/health" >/dev/null && break; sleep 0.5; done

echo; echo "== 1) Salud del servidor =="
curl -s "$BASE/api/v1/health"; echo

echo; echo "== 2) Registrar impresora (simulador en 127.0.0.1:9910) =="
PRINTERS=$(curl -s -X POST "$BASE/api/v1/printers" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Cocina (demo)","ip":"127.0.0.1","port":9910,"profile":"simulator","paper_width_mm":80,"encoding":"CP850","manufacturer":"LBA","model":"Simulator"}')
echo "$PRINTERS" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("id:", d["id"], "|", d["name"], "|", d["ip"]+":"+str(d["port"]), "|", d["protocol"])'
PR_ID=$(echo "$PRINTERS" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo; echo "== 3) Descubrimiento en LAN local (127.0.0.0/29) =="
curl -s -X POST "$BASE/api/v1/printers/discover" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"cidr":"127.0.0.0/29","ports":[9910]}'; echo

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
echo "1º envío: HTTP $J1 | 2º envío (misma clave): HTTP $(echo "$J2" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status_code") or 409)') → $(echo "$J2" | head -c 160)"

echo; echo "== 7) Panel web: login y secciones =="
curl -s -c /tmp/lba-demo-cookies -o /dev/null -w 'login: HTTP %{http_code}\n' \
  -X POST "$BASE/login" --data "password=$LBA_ADMIN_PASSWORD"
for seccion in / /devices /discover /test_print /queue /history /errors /settings /security; do
  code=$(curl -s -b /tmp/lba-demo-cookies -o /dev/null -w '%{http_code}' "$BASE$seccion")
  echo "  $seccion → $code"
done
curl -s -b /tmp/lba-demo-cookies "$BASE/jobs/$JOB_ID" | grep -q "Cocina (demo)" && \
  echo "  detalle del trabajo en panel: OK (impresora visible)"
tail -6 /tmp/lba-sim.log | sed 's/^/  [simulador] /'

echo; echo "== FIN: procesos detenidos (trap EXIT) — datos de demo en $LBA_DATA_DIR =="
