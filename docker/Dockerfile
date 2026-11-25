# syntax=docker/dockerfile:1.7
# ============================================================================
# LBA Print Server — imagen de producción.
# Construir desde la raíz del repositorio:
#   docker build -f docker/Dockerfile -t lba-print-system:1.0.0 .
# ============================================================================
FROM python:3.12-slim-bookworm AS runtime

ARG LBA_VERSION=dev
LABEL org.opencontainers.image.title="LBA Print System" \
      org.opencontainers.image.description="Servidor de impresión ESC/POS para Odoo 19" \
      org.opencontainers.image.version="${LBA_VERSION}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/Lean031110/LBA-PrintSystem"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LBA_DATA_DIR=/data \
    LBA_DB_PATH=/data/lba.db \
    LBA_HOST=0.0.0.0 \
    LBA_PORT=8000 \
    LBA_SIM_PORT=9910 \
    LBA_ROLE=all

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/lba

# Dependencias primero para aprovechar la caché de capas.
COPY server/requirements.txt /opt/lba/server/requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/lba/server/requirements.txt

COPY docker/entrypoint.sh /usr/local/bin/lba-entrypoint
COPY server /opt/lba/server
COPY deploy /opt/lba/deploy
COPY README.md CHANGELOG.md LICENSE VERSION /opt/lba/

RUN printf 'LBA Print System\nVersion: %s\nBuilt from the LBA-PrintSystem release workflow.\n' \
      "${LBA_VERSION}" > /opt/lba/BUILD-INFO.txt \
 && chmod 0755 /usr/local/bin/lba-entrypoint \
 && useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin lba \
 && mkdir -p /data \
 && chown lba:lba /data \
 && chown -R root:root /opt/lba \
 && chmod -R a+rX /opt/lba

USER lba
WORKDIR /opt/lba/server

VOLUME ["/data"]
EXPOSE 8000 9910

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail --silent --show-error "http://127.0.0.1:${LBA_PORT}/api/v1/health" >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/lba-entrypoint"]
