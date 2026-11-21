"""Descubrimiento de impresoras en rango LAN autorizado (escaneo TCP ético).

- Solo CIDR dentro de rangos privados (anti-SSRF; cero Internet).
- Límite de hosts por barrido (1024) para no colgar el servicio.
- Puerto 9100 crudo = 'escpos_raw probable'; 631 IPP; 515 LPD; 80 http.
- El escaneo NO escribe nada en las impresoras (connect + close).
"""
from __future__ import annotations

import asyncio
import ipaddress

from app.core import config

SERVICE_BY_PORT = {9100: "escpos_raw (probable)", 9910: "escpos_raw (LBA simulator)",
                   631: "IPP", 515: "LPD/LPR",
                   80: "http", 443: "https", 9220: "websocket?"}
MAX_HOSTS_PER_SCAN = 1024
CONNECT_TIMEOUT_S = 1.2
MAX_CONCURRENCY = 64


def _network_ok(cidr: str) -> ipaddress.IPv4Network:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise ValueError(f"CIDR no válido: {exc}") from exc
    allowed = [ipaddress.ip_network(n) for n in config.PRINTER_ALLOWED_NETS
               if (":" in n) == (":" in cidr)]
    blocked = [ipaddress.ip_network(n) for n in config.PRINTER_BLOCKED_NETS
               if (":" in n) == (":" in cidr)]

    def _covered(net, nets) -> bool:
        for cand in nets:
            try:
                if net.subnet_of(cand):
                    return True
            except TypeError:   # versiones IP distintas
                continue
        return False

    if _covered(net, blocked):
        raise ValueError("rango bloqueado por política (SSRF)")
    if not _covered(net, allowed) and not net.is_loopback:
        raise ValueError("el rango debe ser una subred de la LAN privada")
    if net.num_addresses > MAX_HOSTS_PER_SCAN:
        raise ValueError(f"rango demasiado grande (máx {MAX_HOSTS_PER_SCAN} hosts)")
    return net


async def _probe(ip: str, port: int, sem: asyncio.Semaphore) -> dict | None:
    async with sem:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=CONNECT_TIMEOUT_S
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # pragma: no cover
                pass
            return {"ip": ip, "port": port,
                    "service": SERVICE_BY_PORT.get(port, "desconocido")}
        except (OSError, asyncio.TimeoutError):
            return None


async def scan(cidr: str, ports: list[int]) -> list[dict]:
    """Devuelve [{ip, port, service}] con puertos abiertos, ordenado."""
    net = _network_ok(cidr)
    hosts = [str(ip) for ip in net.hosts()] or [str(net.network_address)]
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    tasks = [_probe(ip, port, sem) for ip in hosts for port in ports]
    results = await asyncio.gather(*tasks)
    found = sorted((r for r in results if r), key=lambda r: (r["ip"], r["port"]))
    return found
