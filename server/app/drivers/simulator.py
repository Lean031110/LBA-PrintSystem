"""Simulador ESC/POS: impresora falsa de red para probar SIN hardware.

Escucha TCP raw (estilo 9100), acepta bytes y reconstruye el ticket.
Uso:
    python -m app.drivers.simulator --host 127.0.0.1 --port 9910 [--print]
Panel → registra la impresora con IP 127.0.0.1 y puerto 9910, perfil
'simulator'. El worker le envía tickets como a una impresora real y el
panel muestra la vista previa reconstruida.
"""
from __future__ import annotations

import argparse
import logging
import socketserver
import threading

from app.services import preview

log = logging.getLogger("lba.simulator")

RECEIVED: list[bytes] = []          # últimos documentos (para tests)
RECEIVED_LOCK = threading.Lock()
MAX_KEEP = 50


class SimHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:  # pragma: no cover (red)
        blob = bytearray()
        try:
            while True:
                chunk = self.request.recv(65536)
                if not chunk:
                    break
                blob.extend(chunk)
        except OSError:
            pass
        if blob:
            with RECEIVED_LOCK:
                RECEIVED.append(bytes(blob))
                del RECEIVED[:-MAX_KEEP]
            text = preview.render_preview(bytes(blob))
            if PRINT_ENABLED:
                print("\n=== LBA SIMULATOR: ticket recibido "
                      f"({len(blob)} bytes) ===")
                print(text)
                print("=== fin del ticket ===\n", flush=True)


class ThreadingSim(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


PRINT_ENABLED = False


def start(host: str = "127.0.0.1", port: int = 9910,
          echo: bool = True) -> ThreadingSim:
    global PRINT_ENABLED
    PRINT_ENABLED = echo
    srv = ThreadingSim((host, port), SimHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True,
                          name="lba-simulator")
    th.start()
    log.info("simulador ESC/POS escuchando en %s:%s", host, port)
    return srv


def last_documents() -> list[bytes]:
    with RECEIVED_LOCK:
        return list(RECEIVED)


def main() -> None:  # pragma: no cover (CLI)
    parser = argparse.ArgumentParser(description="Simulador de impresora ESC/POS")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9910)
    parser.add_argument("--print", dest="echo", action="store_true",
                        default=True,
                        help="imprime en consola la reconstrucción del ticket")
    parser.add_argument("--quiet", dest="echo", action="store_false")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    srv = start(args.host, args.port, echo=args.echo)
    try:
        threading.Event().wait()  # correr hasta Ctrl+C
    finally:
        srv.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
