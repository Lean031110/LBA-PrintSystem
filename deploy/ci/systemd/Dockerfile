ARG BASE=debian:12
FROM ${BASE}

ENV container=docker \
    DEBIAN_FRONTEND=noninteractive

# systemd como PID 1 dentro del contenedor privilegiado de CI. No es una
# imagen de producción: solo permite validar install.sh/unidades reales.
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod 0755 /usr/sbin/policy-rc.d \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        systemd systemd-sysv dbus procps iproute2 ca-certificates \
    && rm -f /usr/sbin/policy-rc.d \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
