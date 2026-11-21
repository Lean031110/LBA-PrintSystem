"""Motor de rendering: payload estructurado → bytes ESC/POS (python-escpos).

- Usa Dummy para generar bytes y los envía por socket propio (control de
  timeout/reintento uniforme + auditoría de bytes).
- Encoding por impresora: 'AUTO' (magic-encode de escpos, conmuta codepages)
  o codepage fija (ESC t) para clones con firmware limitado.
- NO afirma impresión física: solo devuelve los bytes que se enviaron.
"""
from __future__ import annotations

import base64
import io
from typing import Optional

from escpos.printer import Dummy

from app.core import config
from app.schemas import schemas as S


class RenderError(Exception):
    pass


ESCPOS_PROFILE = "default"   # perfil de capacidades de escpos-printer-db


def _escpos_instance(printer_row) -> Dummy:
    """Crea el Dummy con perfil y encoding según la impresora registrada.

    OJO: el 'profile' LBA (generic/simulator) es solo una etiqueta de gestión;
    el perfil de capacidades de python-escpos se fija a 'default' (compatible
    con clones Rongta/Xprinter; ver docs/COMPATIBILITY.md).
    """
    encoding = printer_row.encoding or config.DEFAULT_ENCODING
    if encoding == "AUTO":
        return Dummy(profile=ESCPOS_PROFILE)
    try:
        return Dummy(profile=ESCPOS_PROFILE,
                     magic_encode_args={"encoding": encoding})
    except Exception:
        # encoding no soportada por el perfil → magic automático
        return Dummy(profile=ESCPOS_PROFILE)


# codecs Python por codepage LBA (para codificación fija de texto)
_CODEC_BY_ENCODING = {
    "CP437": "cp437",
    "CP850": "cp850",
    "CP852": "cp852",
    "Windows-1252": "cp1252",
}


def render_document(printer_row, document: S.TicketDocument,
                     logo_b64: Optional[str] = None,
                     columns: Optional[int] = None) -> bytes:
    """Genera los bytes ESC/POS de un documento completo."""
    p = _escpos_instance(printer_row)
    cols = columns or printer_row.columns or 48
    settings = printer_row.settings or {}
    pset = settings if isinstance(settings, dict) else {}

    fixed_codec = _CODEC_BY_ENCODING.get(printer_row.encoding) \
        if printer_row.encoding and printer_row.encoding != "AUTO" else None
    if fixed_codec:
        # codepage fija: la anunciamos al firmware (ESC t n). charcode() de
        # escpos es no-op cuando magic-encode ya está fijado, así que se
        # emite el comando crudo con el ID de la tabla Epson estándar.
        cp_id = config.ENCODING_TABLE.get(printer_row.encoding)
        if cp_id is not None:
            p._raw(bytes((0x1B, 0x74, cp_id)))

    for block in document.blocks:
        b = block.model_dump()
        t = b["type"]

        if t == "text":
            p.set(align=b.get("align") or "left",
                  bold=b.get("bold") or None,
                  font=b.get("font") or None,
                  width=b.get("width") or None,
                  height=b.get("height") or None)
            for line in b["value"].splitlines() or [""]:
                if fixed_codec:
                    # codepage fija: codificamos nosotros (los caracteres sin
                    # representación se sustituyen por '?', sin conmutar la
                    # página a W-1252 como haría magic-encode)
                    p._raw(line.encode(fixed_codec, errors="replace") + b"\n")
                else:
                    p.textln(line)

        elif t == "ruler":
            p.set(align="center", bold=False, width=1, height=1)
            p.textln((b.get("char") or "-") * min(cols, 48))

        elif t == "feed":
            p.ln(int(b.get("lines") or 0))

        elif t == "cut":
            feed = int(b.get("feed_before") or 0)
            if feed:
                p.ln(feed)
            p.cut()

        elif t == "qr":
            p.set(align="center", bold=False, width=1, height=1)
            try:
                p.qr(b["value"], size=b.get("size") or pset.get("qr_size") or 6,
                     model=b.get("model") or 2)
            except Exception as exc:
                raise RenderError(f"QR no generable: {exc}") from exc

        elif t == "barcode":
            p.set(align="center", bold=False, width=1, height=1)
            try:
                p.barcode(b["value"], b["symbology"],
                          height=int(b.get("height") or 60))
            except Exception:
                # CODE128 y simbologías no soportadas por el firmware del
                # clon: render por software (imagen raster) como fallback.
                try:
                    p.barcode(b["value"], b["symbology"],
                              height=int(b.get("height") or 60),
                              force_software=True)
                except Exception as exc:
                    raise RenderError(
                        f"barcode {b['symbology']} no generable: {exc}") from exc

        elif t == "image":
            if b["source"] == "logo":
                if not logo_b64:
                    raise RenderError("logo no configurado en el servidor")
                data = base64.b64decode(logo_b64)
            else:
                data = base64.b64decode(b["data"])
            img_bytes = io.BytesIO(data)
            try:
                p.image(img_bytes, width=b.get("width") or None)
            except Exception as exc:
                raise RenderError(f"imagen no imprimible: {exc}") from exc

    # cortes automáticos del dispositivo (si el documento no trajo cut y la
    # impresora lo tiene activado)
    if pset.get("cut", True) and not any(
            bb.type == "cut" for bb in document.blocks):
        p.ln(int(pset.get("feed_before_cut") or 3))
        p.cut()

    return p.output


# ------------------------------------------------------------- test tickets

def test_ticket(printer_row, kind: str, company: str,
                logo_b64: Optional[str] = None) -> S.TicketDocument:
    """Tickets de prueba del panel/API. Devuelven payload reutilizable."""
    head = [
        {"type": "text", "value": company or "LBA", "align": "center",
         "bold": True, "width": 2, "height": 1},
        {"type": "text", "value": "TICKET DE PRUEBA", "align": "center"},
        {"type": "text", "value": f"{printer_row.name}", "align": "center"},
        {"type": "text",
         "value": f"{printer_row.manufacturer} {printer_row.model}".strip(),
         "align": "center"},
        {"type": "text", "value": f"IP {printer_row.ip}:{printer_row.port}",
         "align": "center"},
        {"type": "text",
         "value": f"{printer_row.paper_width_mm}mm · {printer_row.encoding} · "
                  f"perfil {printer_row.profile}", "align": "center"},
        {"type": "ruler"},
    ]
    if kind == "caracteres":
        head += [
            {"type": "text", "value": "ñ áéíóú Ñ ÁÉÍÓÚ ü Ü", "align": "center",
             "bold": True},
            {"type": "text", "value": "¿ Estás usando LBA ? ¡ Sí !", "align": "center"},
            {"type": "text", "value": "1 2 3 4 5 6 7 8 9 0", "align": "center"},
            {"type": "text", "value": "€ $ % # @ & * <> [] {} ()", "align": "center"},
            {"type": "feed", "lines": 1},
        ]
    elif kind == "graficos":
        head += [
            {"type": "text", "value": "QR:", "align": "left"},
            {"type": "qr", "value": "https://lba.local/test", "size": 6},
            {"type": "text", "value": "CODE39:", "align": "left"},
            {"type": "barcode", "value": "LBA1234", "symbology": "CODE39"},
            {"type": "text", "value": "EAN13:", "align": "left"},
            {"type": "barcode", "value": "590123412345", "symbology": "EAN13"},
        ]
        if logo_b64:
            head.append({"type": "image", "source": "logo"})
    elif kind == "corte":
        head += [
            {"type": "text", "value": "PRUEBA DE CORTE", "align": "center",
             "bold": True},
            {"type": "text", "value": "Corte tras 3 feeds (parcial en "
                                      "impresoras sin corte total)", "align": "center"},
            {"type": "feed", "lines": 3},
            {"type": "cut"},
        ]
    else:  # basico
        head += [
            {"type": "text", "value": "2 x Pizza Especial .... 18.00"},
            {"type": "text", "value": "1 x Refresco Cola ....... 2.50"},
            {"type": "text", "value": "   » nota: sin cebolla"},
            {"type": "ruler"},
            {"type": "text", "value": "TOTAL ................. 20.50",
             "bold": True},
            {"type": "text", "value": "Gracias por su visita", "align": "center"},
            {"type": "feed", "lines": 2},
        ]
    if kind != "corte":
        head.append({"type": "cut"})
    return S.TicketDocument.model_validate({"type": "ticket", "blocks": head})
