#!/usr/bin/env bash
# ============================================================================
# LBA Print System — arranque de la imagen Docker.
#
# LBA_ROLE:
#   all        API + worker en el mismo contenedor (por defecto)
#   api        solo la API REST y el panel
#   worker     solo el worker de la cola
#   simulator  impresora virtual ESC/POS (papel en /data/simulated-printer)
#
# En modo "all" el simulador solo arranca con LBA_SIM_ENABLED=1.
# ============================================================================
set -euo pipefail

cd /opt/lba/server

export LBA_DATA_DIR="${LBA_DATA_DIR:-/data}"
export LBA_DB_PATH="${LBA_DB_PATH:-${LBA_DATA_DIR}/lba.db}"
export LBA_HOST="${LBA_HOST:-0.0.0.0}"
export LBA_PORT="${LBA_PORT:-8000}"
export LBA_SIM_PORT="${LBA_SIM_PORT:-9910}"
export LBA_SIM_SAVE_DIR="${LBA_SIM_SAVE_DIR:-${LBA_DATA_DIR}/simulated-printer}"
export PYTHONPATH="${PYTHONPATH:-/opt/lba/server}"

ROLE="${LBA_ROLE:-all}"

if ! mkdir -p "${LBA_DATA_DIR}" 2>/dev/null; then
    echo "ERROR: no se pudo crear ${LBA_DATA_DIR} (uid $(id -u))." >&2
    echo "Monte un volumen escribible por el uid 10001 o ajuste LBA_DATA_DIR." >&2
    exit 1
fi
if [[ ! -w "${LBA_DATA_DIR}" ]]; then
    echo "ERROR: ${LBA_DATA_DIR} no es escribible por el uid $(id -u)." >&2
    echo "Con un bind mount: sudo chown -R 10001:10001 <ruta-host>." >&2
    exit 1
fi

api_cmd=(uvicorn app.main:app --host "${LBA_HOST}" --port "${LBA_PORT}" --proxy-headers --no-server-header)
worker_cmd=(python -m app.worker)
sim_cmd=(python -m app.drivers.simulator --host 0.0.0.0 --port "${LBA_SIM_PORT}" --save-dir "${LBA_SIM_SAVE_DIR}")

# Crea esquema y credenciales una sola vez antes de arrancar procesos, para
# que la API y el worker no compitan al inicializar una BD nueva.
init_database() {
    echo "· inicializando SQLite en ${LBA_DB_PATH}"
    python -c 'from app.database.db import init_db; init_db()'
}

case "${ROLE}" in
    api)
        init_database
        exec "${api_cmd[@]}"
        ;;
    worker)
        init_database
        exec "${worker_cmd[@]}"
        ;;
    simulator)
        mkdir -p "${LBA_SIM_SAVE_DIR}"
        exec "${sim_cmd[@]}"
        ;;
    all)
        init_database
        pids=()
        cleanup() {
            for pid in "${pids[@]:-}"; do
                kill -TERM "${pid}" 2>/dev/null || true
            done
            wait 2>/dev/null || true
        }
        trap 'cleanup; exit 0' TERM INT
        "${worker_cmd[@]}" &
        pids+=("$!")
        "${api_cmd[@]}" &
        pids+=("$!")
        if [[ "${LBA_SIM_ENABLED:-0}" == "1" ]]; then
            mkdir -p "${LBA_SIM_SAVE_DIR}"
            "${sim_cmd[@]}" &
            pids+=("$!")
        fi
        # Si cualquiera de los procesos termina, el contenedor termina para
        # que el reinicio de Docker recupere el conjunto completo.
        wait -n "${pids[@]}"
        status=$?
        cleanup
        exit "${status}"
        ;;
    *)
        echo "ERROR: LBA_ROLE='${ROLE}' no es válido (all|api|worker|simulator)." >&2
        exit 2
        ;;
esac
