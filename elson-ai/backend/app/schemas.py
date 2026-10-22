"""Request and response bodies for the HTTP API (pydantic)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models import Bookmark, Document, Position, Progress
from app.normalize.chapters import Chapter
from app.normalize.chunker import Chunk


class ChapterOut(BaseModel):
    index: int
    title: str
    char_start: int
    char_end: int

    @classmethod
    def of(cls, chapter: Chapter) -> ChapterOut:
        return cls(
            index=chapter.index,
            title=chapter.title,
            char_start=chapter.char_start,
            char_end=chapter.char_end,
        )


class DocumentOut(BaseModel):
    id: str
    title: str
    source_kind: str
    status: str = "ready"
    language: str | None
    pipeline_version: str
    char_count: int
    chunk_count: int
    chapters: list[ChapterOut]
    first_audio_ready: bool = False  # becomes true once the TTS pipeline lands (Sprint 2)
    created_at: datetime

    @classmethod
    def of(cls, document: Document) -> DocumentOut:
        return cls(
            id=document.id,
            title=document.title,
            source_kind=document.source_kind,
            language=document.language,
            pipeline_version=document.pipeline_version,
            char_count=len(document.text),
            chunk_count=len(document.chunks),
            chapters=[ChapterOut.of(chapter) for chapter in document.chapters],
            created_at=document.created_at,
        )


class ChunkOut(BaseModel):
    index: int
    char_start: int
    char_end: int
    text: str

    @classmethod
    def of(cls, chunk: Chunk) -> ChunkOut:
        return cls(
            index=chunk.index, char_start=chunk.char_start, char_end=chunk.char_end, text=chunk.text
        )


class ChunkPage(BaseModel):
    items: list[ChunkOut]
    next_start: int | None
    total: int


class ProgressIn(BaseModel):
    char_offset: int = Field(ge=0)
    device_id: str | None = Field(default=None, max_length=64)


class ProgressOut(BaseModel):
    char_offset: int
    pipeline_version: str
    chunk_index: int | None
    chapter_index: int | None
    updated_at: datetime

    @classmethod
    def of(cls, progress: Progress, position: Position) -> ProgressOut:
        return cls(
            char_offset=progress.char_offset,
            pipeline_version=progress.pipeline_version,
            chunk_index=position.chunk_index,
            chapter_index=position.chapter_index,
            updated_at=progress.updated_at,
        )


class BookmarkIn(BaseModel):
    char_offset: int = Field(ge=0)
    label: str = Field(default="", max_length=200)


class BookmarkOut(BaseModel):
    id: str
    char_offset: int
    label: str
    automatic: bool
    created_at: datetime

    @classmethod
    def of(cls, bookmark: Bookmark) -> BookmarkOut:
        return cls(
            id=bookmark.id,
            char_offset=bookmark.char_offset,
            label=bookmark.label,
            automatic=bookmark.automatic,
            created_at=bookmark.created_at,
        )
