"""Impresora virtual ESC/POS para probar SIN hardware.

Escucha TCP raw (estilo 9100), acepta bytes y reconstruye el ticket.
Dos modos de trabajo:

* consola (por defecto): imprime la reconstrucción del ticket en la salida.
* ``--save-dir DIR``: impresora virtual con ``papel`` en disco. Cada documento
  recibido se guarda como ``document-NNNN-<sha>.escpos.bin`` (bytes exactos),
  ``document-NNNN-<sha>.txt`` (reconstrucción legible) y una línea en
  ``documents.jsonl`` con hash, tamaño y hora. Ese archivo es la evidencia
  verificable de que la impresión llegó a la impresora.

Uso:
    python -m app.drivers.simulator --host 127.0.0.1 --port 9910 [--print]
    python -m app.drivers.simulator --port 9910 --save-dir /tmp/papel
Panel → registra la impresora con IP 127.0.0.1 y puerto 9910, perfil
'simulator'. El worker le envía tickets como a una impresora real.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
import socketserver
import threading
from datetime import datetime, timezone

from app.services import preview

log = logging.getLogger("lba.simulator")

RECEIVED: list[bytes] = []          # últimos documentos (para tests)
RECEIVED_LOCK = threading.Lock()
MAX_KEEP = 50

SAVE_DIR: Path | None = None        # impresora virtual con papel en disco
_SEQUENCE = 0


def _persist_document(blob: bytes, text: str) -> None:
    """Escribe el documento recibido como evidencia de impresión."""
    if SAVE_DIR is None:
        return
    digest = hashlib.sha256(blob).hexdigest()
    with RECEIVED_LOCK:
        global _SEQUENCE
        _SEQUENCE += 1
        sequence = _SEQUENCE
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        base = f"document-{sequence:04d}-{digest[:8]}"
        bin_path = SAVE_DIR / f"{base}.escpos.bin"
        txt_path = SAVE_DIR / f"{base}.txt"
        bin_path.write_bytes(blob)
        txt_path.write_text(text, encoding="utf-8", errors="replace")
        with (SAVE_DIR / "documents.jsonl").open("a", encoding="utf-8") as journal:
            journal.write(json.dumps({
                "sequence": sequence,
                "received_at": stamp,
                "bytes": len(blob),
                "sha256": digest,
                "bin_file": bin_path.name,
                "text_file": txt_path.name,
            }, sort_keys=True) + "\n")
    log.info("documento %s impreso en papel virtual (%d bytes)", base, len(blob))


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
            try:
                text = preview.render_preview(bytes(blob))
            except Exception:  # un ticket raro nunca debe perder la evidencia
                log.exception("no se pudo reconstruir el ticket; se guarda texto crudo")
                text = bytes(blob).decode("latin-1", "replace")
            _persist_document(bytes(blob), text)
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
          echo: bool = True, save_dir: str | Path | None = None) -> ThreadingSim:
    global PRINT_ENABLED, SAVE_DIR
    PRINT_ENABLED = echo
    if save_dir is not None:
        SAVE_DIR = Path(save_dir)
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
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
    parser.add_argument(
        "--save-dir", default=None,
        help="guarda cada documento como .escpos.bin + .txt (papel virtual)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    srv = start(args.host, args.port, echo=args.echo, save_dir=args.save_dir)
    try:
        threading.Event().wait()  # correr hasta Ctrl+C
    finally:
        srv.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
