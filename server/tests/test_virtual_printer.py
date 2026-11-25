"""Impresora virtual: cada documento recibido queda como evidencia en disco."""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import pytest

from app.drivers import simulator
from app.services import preview


def _send(port: int, blob: bytes) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(blob)


def _wait_documents(directory: Path, expected: int, timeout: float = 5.0) -> list[dict]:
    journal = directory / "documents.jsonl"
    deadline = time.time() + timeout
    entries: list[dict] = []
    while time.time() < deadline:
        if journal.exists():
            entries = [json.loads(line) for line in
                       journal.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(entries) >= expected:
                return entries
        time.sleep(0.05)
    return entries


@pytest.fixture()
def virtual_printer(tmp_path: Path):
    simulator.RECEIVED.clear()
    simulator._SEQUENCE = 0
    srv = simulator.start("127.0.0.1", 0, echo=False, save_dir=tmp_path)
    try:
        yield srv.server_address[1], tmp_path
    finally:
        srv.shutdown()
        srv.server_close()
        simulator.SAVE_DIR = None
        simulator.RECEIVED.clear()


def test_preview_unknown_escape_does_not_hang() -> None:
    """Un ESC no reconocido debe consumirse, no bloquear el parser."""
    blob = b"\x1b@TICKET\n" + bytes(range(30))
    text = preview.render_preview(blob)
    assert "TICKET" in text


def test_virtual_printer_saves_bin_text_and_journal(virtual_printer) -> None:
    port, directory = virtual_printer
    first = b"\x1b@TICKET UNO\n" + bytes(range(30))
    second = b"\x1b@TICKET DOS\n"

    _send(port, first)
    _send(port, second)
    entries = _wait_documents(directory, 2)

    assert len(entries) == 2
    for entry in entries:
        bin_path = directory / entry["bin_file"]
        text_path = directory / entry["text_file"]
        assert bin_path.is_file() and text_path.is_file()
        assert bin_path.read_bytes() in (first, second)
        assert text_path.read_text(encoding="utf-8").strip()

    assert [entry["sequence"] for entry in entries] == [1, 2]
    assert len({entry["sha256"] for entry in entries}) == 2
    assert entries[0]["bytes"] == len(first)
    assert entries[1]["received_at"].endswith("+00:00")
