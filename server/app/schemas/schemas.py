"""Contratos Pydantic del payload estructurado de impresión (/api/v1 y panel).

Reglas: nunca se aceptan rutas de archivo, comandos crudos ni binarios —
solo bloques declarativos que el servidor traduce a ESC/POS.
"""
from __future__ import annotations

import base64
import binascii
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core import config

Align = Literal["left", "center", "right"]
Encoding = Literal["AUTO", "CP437", "CP850", "CP852", "Windows-1252"]
Symbology = Literal["EAN13", "EAN8", "UPC-A", "UPC-E", "CODE128", "CODE39", "ITF"]


# ------------------------------------------------------------------- bloques

class TextBlock(BaseModel):
    type: Literal["text"]
    value: str = Field(..., max_length=config.MAX_TEXT_CHARS)
    align: Optional[Align] = None
    bold: Optional[bool] = None
    width: Optional[int] = Field(None, ge=1, le=8)
    height: Optional[int] = Field(None, ge=1, le=8)
    font: Optional[Literal["a", "b"]] = None

    model_config = ConfigDict(str_strip_whitespace=False)


class RulerBlock(BaseModel):
    type: Literal["ruler"]
    char: str = Field("-", min_length=1, max_length=1)


class FeedBlock(BaseModel):
    type: Literal["feed"]
    lines: int = Field(0, ge=0, le=20)


class CutBlock(BaseModel):
    type: Literal["cut"]
    feed_before: int = Field(3, ge=0, le=20)


class QrBlock(BaseModel):
    type: Literal["qr"]
    value: str = Field(..., max_length=config.MAX_QR_CHARS)
    size: Optional[int] = Field(None, ge=1, le=16)
    model: Optional[Literal[1, 2]] = None


class BarcodeBlock(BaseModel):
    type: Literal["barcode"]
    value: str = Field(..., max_length=100)
    symbology: Symbology
    height: Optional[int] = Field(None, ge=1, le=255)

    @model_validator(mode="after")
    def _validate_value(self) -> "BarcodeBlock":
        v, sym = self.value, self.symbology
        digits = v.replace(" ", "")
        if sym in ("EAN13", "UPC-A") and not (digits.isdigit() and len(digits) in (11, 12, 13)):
            raise ValueError(f"{sym} requiere 11-13 dígitos")
        if sym == "EAN8" and not (digits.isdigit() and len(digits) in (7, 8)):
            raise ValueError("EAN8 requiere 7-8 dígitos")
        if sym == "UPC-E" and not (digits.isdigit() and len(digits) in (6, 7, 8)):
            raise ValueError("UPC-E requiere 6-8 dígitos")
        if sym == "CODE39" and not all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-.$/+% " for c in v):
            raise ValueError("CODE39 solo admite A-Z 0-9 y - . $ / + % espacio")
        if sym == "ITF" and not digits.isdigit():
            raise ValueError("ITF requiere solo dígitos")
        return self


class ImageBlock(BaseModel):
    type: Literal["image"]
    source: Literal["logo", "base64"]
    data: Optional[str] = None
    width: Optional[int] = Field(None, ge=1, le=576)

    @model_validator(mode="after")
    def _validate_source(self) -> "ImageBlock":
        if self.source == "base64":
            if not self.data:
                raise ValueError("source=base64 requiere 'data'")
            try:
                raw = base64.b64decode(self.data, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("base64 inválido") from exc
            if len(raw) > config.MAX_IMAGE_B64_KB * 1024:
                raise ValueError(f"imagen > {config.MAX_IMAGE_B64_KB} KB")
        return self


Block = Annotated[
    Union[TextBlock, RulerBlock, FeedBlock, CutBlock, QrBlock, BarcodeBlock, ImageBlock],
    Field(discriminator="type"),
]


class TicketDocument(BaseModel):
    type: Literal["ticket"]
    blocks: List[Block] = Field(..., min_length=1, max_length=config.MAX_BLOCKS)

    @field_validator("blocks")
    @classmethod
    def _non_empty(cls, v):
        if not v:
            raise ValueError("el documento necesita al menos un bloque")
        return v


# ------------------------------------------------------------------- trabajos

class JobCreate(BaseModel):
    printer_id: str = Field(..., min_length=8, max_length=36)
    idempotency_key: Optional[str] = Field(
        None, max_length=200,
        pattern=r"^[A-Za-z0-9_:\-.]+$",
    )
    origin: Literal["api", "odoo", "panel", "test", "reprint"] = "api"
    metadata: Optional[Dict[str, Any]] = None
    document: TicketDocument

    @field_validator("metadata")
    @classmethod
    def _meta_small(cls, v):
        if v is None:
            return {}
        if len(str(v)) > 4000:
            raise ValueError("metadata demasiado grande (≤4000 chars)")
        return v


class PrinterSettings(BaseModel):
    cut: bool = True
    feed_before_cut: int = Field(3, ge=0, le=20)
    density: Optional[int] = Field(None, ge=-8, le=8)
    logo: bool = False
    qr_size: int = Field(6, ge=1, le=16)


class PrinterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    manufacturer: str = Field("", max_length=60)
    model: str = Field("", max_length=60)
    profile: Literal["generic", "simulator"] = "generic"
    port: int = Field(9100, ge=1, le=65535)
    paper_width_mm: Literal[58, 80] = 80
    encoding: Encoding = config.DEFAULT_ENCODING
    notes: str = Field("", max_length=2000)
    active: bool = True
    settings: PrinterSettings = Field(default_factory=PrinterSettings)


class PrinterCreate(PrinterBase):
    ip: str = Field(..., max_length=60)


class PrinterUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    manufacturer: Optional[str] = Field(None, max_length=60)
    model: Optional[str] = Field(None, max_length=60)
    profile: Optional[Literal["generic", "simulator"]] = None
    ip: Optional[str] = Field(None, max_length=60)
    port: Optional[int] = Field(None, ge=1, le=65535)
    paper_width_mm: Optional[Literal[58, 80]] = None
    encoding: Optional[Encoding] = None
    notes: Optional[str] = Field(None, max_length=2000)
    active: Optional[bool] = None
    settings: Optional[PrinterSettings] = None


class DiscoverRequest(BaseModel):
    cidr: str = Field(..., max_length=60)
    ports: List[int] = Field(default_factory=lambda: [9100],
                             max_length=6)

    @field_validator("ports")
    @classmethod
    def _ports_ok(cls, v):
        if not v:
            return [9100]
        for p in v:
            if not (1 <= p <= 65535):
                raise ValueError("puerto fuera de rango")
        return v


class TestPrintRequest(BaseModel):
    kind: Literal["basico", "caracteres", "graficos", "corte"] = "basico"
