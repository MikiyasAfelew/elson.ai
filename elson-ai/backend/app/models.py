"""Domain models. Plain dataclasses, so the service layer has no web-framework dependency."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.normalize.chapters import Chapter
from app.normalize.chunker import Chunk


@dataclass
class Document:
    id: str
    user_id: str
    title: str
    source_kind: str
    filename: str
    created_at: datetime
    text: str  # canonical text; chunk, chapter, progress and bookmark offsets point into it
    chapters: list[Chapter]
    chunks: list[Chunk]
    pipeline_version: str
    language: str | None = None  # language detection arrives with the second language (Sprint 7)


@dataclass(frozen=True)
class Progress:
    char_offset: int
    pipeline_version: str
    device_id: str | None
    updated_at: datetime


@dataclass(frozen=True)
class Bookmark:
    id: str
    char_offset: int
    label: str
    automatic: bool  # True for the position kept when another device overwrote it
    created_at: datetime


@dataclass(frozen=True)
class Position:
    """A character offset resolved to the chunk and chapter that contain it."""

    char_offset: int
    chunk_index: int | None
    chapter_index: int | None
