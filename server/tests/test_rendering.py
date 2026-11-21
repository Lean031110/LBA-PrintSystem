"""Motor de rendering ESC/POS: codepages ES, QR, barcode, corte, fallback."""
from __future__ import annotations

import pytest

from app.models import models
from app.schemas import schemas as S
from app.services import preview, rendering


class _P:
    """Impresora falsa para rendering directo."""
    def __init__(self, encoding="CP850", width=80):
        self.profile = "generic"
        self.encoding = encoding
        self.paper_width_mm = width
        self.columns = 32 if width == 58 else 48
        self.settings = {"cut": True, "feed_before_cut": 3, "qr_size": 6}


def _doc(blocks):
    return S.TicketDocument.model_validate({"type": "ticket", "blocks": blocks})


def test_texto_espanol_cp850():
    blob = rendering.render_document(_P(), _doc([
        {"type": "text", "value": "PIZZERÍA — ñ áéíóú ¿¡", "bold": True},
    ]))
    assert b"\x1bE\x01" in blob            # negrita ESC E 1
    # CP850 fija: ESC t 2 (codepage 2) y bytes de acentos correctos
    assert b"\x1bt\x02" in blob
    assert "á".encode("cp850") in blob
    assert "ñ".encode("cp850") in blob
    assert "¿".encode("cp850") in blob


def test_corte_presente_gs_v():
    blob = rendering.render_document(_P(), _doc([
        {"type": "text", "value": "GRACIAS"},
        {"type": "cut", "feed_before": 2},
    ]))
    assert b"\x1dV" in blob                  # GS V
    assert b"GRACIAS" in blob


def test_qr_y_barcode():
    blob = rendering.render_document(_P(), _doc([
        {"type": "qr", "value": "https://lba.local/t/00042", "size": 6},
        {"type": "barcode", "value": "590123412345", "symbology": "EAN13"},
    ]))
    assert len(blob) > 200
    assert b"\x1dk" in blob                  # GS k (barcode por hardware)


def test_barcode_code128_fallback_software():
    # CODE128 no renderiza por hardware en escpos 3.1 → software (imagen)
    blob = rendering.render_document(_P(), _doc([
        {"type": "barcode", "value": "LBA-0001", "symbology": "CODE128"},
    ]))
    assert len(blob) > 400                   # raster de imagen > bytes GS k


def test_alineaciones_y_ancho_58():
    p = _P(width=58)
    blob = rendering.render_document(p, _doc([
        {"type": "text", "value": "centrado", "align": "center"},
        {"type": "ruler"},
    ]))
    assert b"\x1ba\x01" in blob              # ESC a 1 (center)
    # regla limitada a las columnas del papel (58mm → 32)
    assert (b"-" * 32) in blob


def test_preview_reconstruye_texto_y_corte():
    blob = rendering.render_document(_P(), _doc([
        {"type": "text", "value": "HOLA ñ á"},
        {"type": "cut"},
    ]))
    text = preview.render_preview(blob, codec="CP850")
    assert "HOLA" in text
    assert "[CORTE]" in text
    assert "á" in text or "a" in text        # decodificable, sin romper


def test_encoding_auto_no_explota():
    blob = rendering.render_document(_P(encoding="AUTO"), _doc([
        {"type": "text", "value": "ñ áéíóú ¿¡ €"},
    ]))
    assert len(blob) > 10                    # magic-encode conmuta codepages
