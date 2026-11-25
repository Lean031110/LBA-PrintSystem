#!/usr/bin/env bash
# ============================================================================
# LBA PRINT SYSTEM — prueba de humo de la imagen Docker.
#
# Construye la imagen, arranca API+worker y una impresora virtual en contenedores
# separados, registra la impresora por API, envía una impresión y exige:
#   * contenedor sin root (uid 10001);
#   * /api/v1/health 200;
#   * trabajo en estado `sent`;
#   * documento materializado en documents.jsonl de la impresora virtual;
#   * persistencia tras reiniciar el contenedor de la API.
#
# Uso: bash deploy/ci/docker_smoke_test.sh [imagen]
# Requiere: docker con daemon accesible y curl.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${1:-lba-print:ci}"
NET="lba-smoke-net"
API="lba-smoke-api"
SIM="lba-smoke-sim"
VOL="lba-smoke-data"
HOST_PORT="${LBA_SMOKE_PORT:-18000}"
BASE="http://127.0.0.1:${HOST_PORT}"
TOKEN="smoke-token-0123456789abcdef0123456789"
ADMIN_PW="smoke-admin-password-1234"

LOGS="$(mktemp -d "${TMPDIR:-/tmp}/lba-docker-smoke-XXXXXX")"

cleanup() {
    local rc=$?
    if (( rc != 0 )); then
        echo "---- docker logs api ----" >&2
        docker logs "$API" 2>&1 | tail -80 >&2 || true
        echo "---- docker logs sim ----" >&2
        docker logs "$SIM" 2>&1 | tail -40 >&2 || true
        echo "---- documents ----" >&2
        docker exec "$SIM" sh -c 'cat /data/sim/documents.jsonl' 2>&1 | tail -5 >&2 || true
    fi
    docker rm -f "$API" "$SIM" >/dev/null 2>&1 || true
    docker volume rm -f "$VOL" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    rm -rf -- "$LOGS"
    exit "$rc"
}
trap cleanup EXIT INT TERM

echo "== Construir la imagen $IMAGE =="
docker build -f "$ROOT/docker/Dockerfile" -t "$IMAGE" "$ROOT"

echo "== Red y volumen aislados =="
docker network create "$NET" >/dev/null
docker volume create "$VOL" >/dev/null

echo "== Arrancar impresora virtual =="
docker run -d --name "$SIM" --network "$NET" \
    -e LBA_ROLE=simulator \
    -e LBA_SIM_SAVE_DIR=/data/sim \
    -v "$VOL:/data" \
    "$IMAGE" >/dev/null

echo "== Arrancar API + worker =="
docker run -d --name "$API" --network "$NET" \
    -p "${HOST_PORT}:8000" \
    -e LBA_ROLE=all \
    -e LBA_API_TOKEN="$TOKEN" \
    -e LBA_ADMIN_PASSWORD="$ADMIN_PW" \
    -v "$VOL:/data" \
    "$IMAGE" >/dev/null

echo "== Esperar /api/v1/health =="
READY=0
for _ in $(seq 1 60); do
    if curl --fail --silent --show-error "$BASE/api/v1/health" > "$LOGS/health.json"; then
        READY=1
        break
    fi
    sleep 1
done
if (( READY != 1 )); then
    echo "La API no respondió; estado: $(docker inspect -f '{{.State.Status}}' "$API" 2>/dev/null || true)" >&2
    exit 1
fi
cat "$LOGS/health.json"
echo

echo "== Verificar que el contenedor no corre como root =="
UID_RUNNING="$(docker exec "$API" id -u)"
[[ "$UID_RUNNING" == "10001" ]] || { echo "uid inesperado: $UID_RUNNING" >&2; exit 1; }
echo "uid=$UID_RUNNING (lba)"

echo "== Registrar la impresora virtual por API =="
# La API valida una IP literal (anti-SSRF): se resuelve la IP del contenedor.
SIM_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$SIM")"
[[ -n "$SIM_IP" ]] || { echo "no se pudo resolver la IP de $SIM" >&2; exit 1; }
echo "impresora virtual: $SIM ($SIM_IP:9910)"
PRINTER_JSON="$(curl --fail --silent --show-error -X POST "$BASE/api/v1/printers" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"name\":\"Docker smoke\",\"ip\":\"$SIM_IP\",\"port\":9910,\"profile\":\"simulator\",\"paper_width_mm\":80,\"encoding\":\"CP850\"}")"
echo "$PRINTER_JSON"
PRINTER_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$PRINTER_JSON")"

echo "== Enviar impresión de prueba =="
JOB_JSON="$(curl --fail --silent --show-error -X POST "$BASE/api/v1/printers/$PRINTER_ID/test" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"kind":"caracteres"}')"
JOB_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$JOB_JSON")"

STATUS=""
for _ in $(seq 1 60); do
    STATUS="$(curl --fail --silent --show-error "$BASE/api/v1/jobs/$JOB_ID" \
        -H "Authorization: Bearer $TOKEN" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
    [[ "$STATUS" == "sent" ]] && break
    sleep 1
done
[[ "$STATUS" == "sent" ]] || { echo "estado final inesperado: $STATUS" >&2; exit 1; }
echo "trabajo $JOB_ID → $STATUS"

echo "== Exigir el documento en la impresora virtual =="
docker exec "$SIM" sh -c 'test -s /data/sim/documents.jsonl'
docker exec "$SIM" sh -c 'ls /data/sim/*.txt /data/sim/*.escpos.bin >/dev/null'
docker exec "$SIM" sh -c 'tail -1 /data/sim/documents.jsonl'
echo
echo "documentos en disco verificados"

echo "== Reiniciar la API y comprobar persistencia =="
docker restart "$API" >/dev/null
READY=0
for _ in $(seq 1 60); do
    if curl --fail --silent --show-error "$BASE/api/v1/health" >/dev/null; then
        READY=1
        break
    fi
    sleep 1
done
(( READY == 1 )) || { echo "la API no volvió tras reiniciar" >&2; exit 1; }
JOB_STATUS="$(curl --fail --silent --show-error "$BASE/api/v1/jobs/$JOB_ID" \
    -H "Authorization: Bearer $TOKEN" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
[[ "$JOB_STATUS" == "sent" ]] || { echo "el trabajo se perdió tras reiniciar: $JOB_STATUS" >&2; exit 1; }
echo "trabajo persistido tras reinicio: $JOB_STATUS"

echo "== Verificar que docker compose es válido =="
(cd "$ROOT" && LBA_IMAGE="$IMAGE" LBA_VERSION=smoke \
    docker compose -f docker/docker-compose.yml config --quiet)

echo "DOCKER SMOKE OK"
