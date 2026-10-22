"""Decide what kind of file an upload is, from its name and its first bytes."""

from __future__ import annotations

from pathlib import PurePath

_TEXT_EXTENSIONS = {".txt", ".text", ""}


def safe_filename(filename: str | None) -> str:
    """The final path component only, so a hostile name like "../../x" cannot leak a path."""
    if not filename:
        return ""
    return PurePath(filename.replace("\\", "/")).name


def detect_kind(filename: str | None, head: bytes) -> str:
    """Return "txt", "epub", "pdf", "docx" or "unknown"."""
    extension = PurePath(safe_filename(filename)).suffix.lower()
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):  # a zip container
        if extension == ".epub":
            return "epub"
        if extension == ".docx":
            return "docx"
        return "unknown"
    if extension == ".pdf" or extension == ".epub" or extension == ".docx":
        return "unknown"  # the name promises a format the bytes do not deliver
    if extension in _TEXT_EXTENSIONS:
        return "txt"
    return "unknown"


def title_from_filename(filename: str | None) -> str:
    stem = PurePath(safe_filename(filename)).stem
    title = " ".join(stem.replace("_", " ").replace("-", " ").split())
    return title or "Untitled"
