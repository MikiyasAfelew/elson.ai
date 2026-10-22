"""File ingestion: turn an uploaded file into raw text.

Only plain text is supported so far. EPUB arrives in Sprint 4 and text-based PDF in Sprint 5; the
detection below already recognizes them so users get an honest message instead of garbled audio.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.errors import AppError
from app.ingestion.kinds import detect_kind, safe_filename, title_from_filename
from app.ingestion.txt import decode_text

__all__ = ["ExtractedText", "extract_text", "safe_filename"]

_COMING_SOON = {
    "epub": "EPUB books are coming soon. For now, please upload a plain text file.",
    "pdf": "PDF files are coming soon. For now, please upload a plain text file.",
    "docx": "Word documents are coming soon. For now, please upload a plain text file.",
}


@dataclass(frozen=True)
class ExtractedText:
    kind: str
    text: str
    title: str


def extract_text(filename: str | None, data: bytes) -> ExtractedText:
    kind = detect_kind(filename, data[:16])
    if kind in _COMING_SOON:
        raise AppError("NOT_YET_SUPPORTED", _COMING_SOON[kind], status_code=415)
    if kind != "txt":
        raise AppError(
            "UNSUPPORTED_FILE",
            "This file type is not supported. Try a plain text file.",
            status_code=415,
        )
    return ExtractedText("txt", decode_text(data), title_from_filename(filename))
