"""Reconstrucción textual de bytes ESC/POS (vista previa en el panel).

Parser de subconjunto (best-effort, con marcadores): texto, saltos,
alineación implícita, corte, QR/barcode/imagen y codepages.
"""
from __future__ import annotations

CODEPAGE_CODECS = {
    0: "cp437", 2: "cp850", 3: "cp860", 4: "cp863", 5: "cp865",
    11: "cp851", 13: "cp857", 15: "cp858", 16: "cp1252",
    17: "cp866", 18: "cp852", 19: "cp858", 255: "cp437",
}


def render_preview(data: bytes, codec: str = "cp850", columns: int = 48) -> str:
    """Devuelve texto legible aproximado de lo que se envió a la impresora."""
    lines: list[str] = []
    cur: list[str] = []
    codec_cur = codec if codec != "AUTO" else "cp437"
    i, n = 0, len(data)

    def flush() -> None:
        text = "".join(cur)
        cur.clear()
        if text.strip() == "" and not text:
            lines.append("")
        else:
            lines.append(text)

    def emit(txt: str) -> None:
        cur.append(txt)

    while i < n:
        b = data[i]
        if b == 0x0A:  # LF
            flush()
            i += 1
        elif b == 0x0D:
            i += 1
        elif b == 0x1B:  # ESC
            if i + 1 >= n:
                break
            c = data[i + 1]
            if c == 0x40:          # ESC @ init
                i += 2
            elif c == 0x74:         # ESC t n → codepage
                if i + 2 < n:
                    cp = data[i + 2]
                    codec_cur = CODEPAGE_CODECS.get(cp, "cp437")
                    i += 3
                else:
                    i += 2
            elif c == 0x64:         # ESC d n → n saltos
                if i + 2 < n:
                    flush()
                    k = data[i + 2]
                    lines.extend([""] * max(0, min(k, 20)))
                    i += 3
                else:
                    i += 2
            elif c == 0x4A:        # ESC J n (dots)
                flush()
                i += 3 if i + 2 < n else 2
            elif c == 0x2A:        # ESC * bit image
                if i + 4 < n:
                    m, xl, xh = data[i + 2], data[i + 3], data[i + 4]
                    x = xl + (xh << 8)
                    length = x * (m + 1)
                    emit("[IMAGEN]")
                    flush()
                    i += 5 + length
                else:
                    break
            elif c in (0x45, 0x47, 0x61, 0x21, 0x7B, 0x4D, 0x20, 0x32, 0x33, 0x04):
                # ESC E/G/a/!/{/M/SP/2/3/DLE-EOT: 1 argumento
                i += 3
            else:
                # Comando ESC desconocido: consumirlo para no entrar en un
                # bucle infinito con payloads que incluyan bytes de control.
                i += 2
        elif b == 0x1D:  # GS
            if i + 1 >= n:
                break
            c = data[i + 1]
            if c == 0x56:          # GS V corte
                flush()
                lines.append("[CORTE]")
                i += 2
                if i < n and data[i] == 66:
                    i += 3
                elif i < n and data[i] in (0, 1, 48, 49):
                    i += 1
            elif c == 0x6B:        # GS k barcode
                flush()
                lines.append("[CODIGO DE BARRAS]")
                i += 2
                if i < n:
                    k = data[i]
                    i += 1 + min(k, 255)
            elif c == 0x28:        # GS ( k (QR y otros)
                flush()
                if i + 2 < n and data[i + 2] == 0x6B:
                    lines.append("[QR]")
                else:
                    lines.append("[COMANDO GS( )]")
                if i + 4 < n:
                    # GS ( k pL pH ...: pL/pH cuentan los bytes a continuación
                    # (incluidos cn/fn). No interpretar el payload como texto.
                    length = data[i + 3] + (data[i + 4] << 8)
                    i = min(n, i + 5 + length)
                else:
                    # Cabecera incompleta: conservar el preview best-effort y
                    # no exponer bytes binarios restantes como si fueran texto.
                    i = n
            elif c == 0x76:        # GS v 0 raster
                if i + 7 < n and data[i + 2] in (0x30, 0x31, 0x00, 0x01):
                    xL, xH, yL, yH = data[i + 3], data[i + 4], data[i + 5], data[i + 6]
                    x = xL + (xH << 8)
                    y = yL + (yH << 8)
                    flush()
                    lines.append("[IMAGEN]")
                    i += 7 + x * y
                else:
                    i += 2
            elif c in (0x68, 0x77, 0x48, 0x66, 0x42, 0x21, 0x65):  # GS h/w/H/f/B/!/E
                i += 3
            else:
                i += 2
        else:
            # byte de texto en la codepage activa
            chunk = data[i:i + 1]
            try:
                emit(chunk.decode(codec_cur, errors="replace"))
            except Exception:
                emit("?")
            i += 1
    flush()
    # limpieza final: lineas vacías al final
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
