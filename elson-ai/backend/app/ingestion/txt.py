"""Decode plain-text uploads into a string."""

from __future__ import annotations

import codecs

from app.errors import AppError

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode_text(data: bytes) -> str:
    """Decode bytes using a BOM if present, then UTF-8, then Windows-1252.

    Raises AppError when the data looks binary rather than text.
    """
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding, errors="replace")
    if b"\x00" in data[:8192]:
        raise AppError(
            "UNSUPPORTED_FILE",
            "This file doesn't look like text. Try a plain text file.",
            status_code=415,
        )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Windows-1252 is what most legacy .txt files use; undefined bytes become U+FFFD.
        return data.decode("cp1252", errors="replace")
