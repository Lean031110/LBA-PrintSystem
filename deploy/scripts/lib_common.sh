#!/usr/bin/env bash
# Utilidades compartidas para instalador/actualizador LBA.
# No desactiva TLS, validación GPG ni otras comprobaciones de integridad.

lba_die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

lba_require_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        lba_die "ejecuta este comando como root dentro del contenedor."
    fi
}

lba_run_as_user() {
    local user="$1"
    shift
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$user" -- "$@"
        return
    fi
    lba_die "no se encontró runuser (paquete util-linux); no se recurrirá a sudo implícitamente."
}

# Uso: lba_retry "descripción" comando arg...
# LBA_DOWNLOAD_RETRIES es el máximo total de intentos (default 5).
# LBA_RETRY_BASE_SECONDS, LBA_RETRY_MAX_SECONDS y
# LBA_RETRY_JITTER_SECONDS permiten ajustar backoff/jitter.
lba_retry() {
    local label="$1"
    shift
    local attempts="${LBA_DOWNLOAD_RETRIES:-5}"
    local base="${LBA_RETRY_BASE_SECONDS:-2}"
    local cap="${LBA_RETRY_MAX_SECONDS:-45}"
    local jitter_max="${LBA_RETRY_JITTER_SECONDS:-3}"
    local attempt=1 delay jitter rc i

    [[ "$attempts" =~ ^[1-9][0-9]*$ ]] || lba_die "LBA_DOWNLOAD_RETRIES debe ser entero positivo."
    [[ "$base" =~ ^[0-9]+$ ]] || lba_die "LBA_RETRY_BASE_SECONDS debe ser entero no negativo."
    [[ "$cap" =~ ^[1-9][0-9]*$ ]] || lba_die "LBA_RETRY_MAX_SECONDS debe ser entero positivo."
    [[ "$jitter_max" =~ ^[0-9]+$ ]] || lba_die "LBA_RETRY_JITTER_SECONDS debe ser entero no negativo."
    (( ${#attempts} <= 2 && ${#base} <= 4 && ${#cap} <= 4 && ${#jitter_max} <= 3 )) || \
        lba_die "la configuración de reintentos excede los rangos admitidos."
    attempts=$((10#$attempts))
    base=$((10#$base))
    cap=$((10#$cap))
    jitter_max=$((10#$jitter_max))
    (( attempts <= 20 )) || lba_die "LBA_DOWNLOAD_RETRIES no puede superar 20."
    (( base <= 3600 )) || lba_die "LBA_RETRY_BASE_SECONDS no puede superar 3600."
    (( cap <= 3600 )) || lba_die "LBA_RETRY_MAX_SECONDS no puede superar 3600."
    (( jitter_max <= 300 )) || lba_die "LBA_RETRY_JITTER_SECONDS no puede superar 300."

    while (( attempt <= attempts )); do
        printf '[%s] intento %d/%d\n' "$label" "$attempt" "$attempts"
        if "$@"; then
            return 0
        else
            rc=$?
        fi
        if (( attempt == attempts )); then
            printf '[%s] agotados los reintentos (código %d).\n' "$label" "$rc" >&2
            return "$rc"
        fi
        delay="$base"
        if (( delay > cap )); then
            delay="$cap"
        fi
        for ((i=1; i<attempt && delay<cap; i++)); do
            delay=$((delay * 2))
            if (( delay > cap )); then
                delay="$cap"
            fi
        done
        jitter=0
        if (( jitter_max > 0 )); then
            jitter=$((RANDOM % (jitter_max + 1)))
        fi
        printf '[%s] reintento en %d s (base=%d, jitter=%d).\n' \
            "$label" "$((delay + jitter))" "$delay" "$jitter"
        sleep "$((delay + jitter))"
        attempt=$((attempt + 1))
    done
}
