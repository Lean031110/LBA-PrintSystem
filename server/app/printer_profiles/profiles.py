"""Perfiles de impresora LBA.

'generic'  → cualquier impresora de red ESC/POS raw 9100 (Rongta, Xprinter, Epson…).
'simulator'→ endpoint del emulador LBA (pruebas sin hardware).

No se afirma compatibilidad de un modelo concreto sin verificación física:
la matriz y la guía están en docs/COMPATIBILITY.md.
"""
from __future__ import annotations

PROFILES: dict[str, dict] = {
    "generic": {
        "key": "generic",
        "label": "Genérica ESC/POS (red)",
        "protocol": "escpos_raw_tcp",
        "default_port": 9100,
        "capabilities": {"text": True, "qr": True, "barcode": True,
                         "image": True, "cut": True},
        "notes": "Perfil por defecto; verificar QR/barcode/corte con ticket de prueba.",
    },
    "simulator": {
        "key": "simulator",
        "label": "LBA Simulator (emulador local)",
        "protocol": "escpos_raw_tcp",
        "default_port": 9910,
        "capabilities": {"text": True, "qr": True, "barcode": True,
                         "image": True, "cut": True},
        "notes": "Acepta bytes ESC/POS y permite vista previa en el panel.",
    },
}


def profile_exists(key: str) -> bool:
    return key in PROFILES


def default_port(key: str) -> int:
    return PROFILES.get(key, PROFILES["generic"])["default_port"]
