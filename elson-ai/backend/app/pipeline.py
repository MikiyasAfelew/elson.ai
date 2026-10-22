"""The text pipeline: raw text in, canonical text + chapters + chunks out."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import PIPELINE_VERSION
from app.normalize.chapters import Chapter, detect_chapters
from app.normalize.chunker import DEFAULT_CHUNK_CONFIG, Chunk, ChunkConfig, chunk_text
from app.normalize.cleaner import clean_text


@dataclass(frozen=True)
class ProcessedDocument:
    text: str  # canonical text; every offset below points into it
    chapters: list[Chapter]
    chunks: list[Chunk]
    pipeline_version: str


def process_text(raw: str, config: ChunkConfig = DEFAULT_CHUNK_CONFIG) -> ProcessedDocument:
    canonical = clean_text(raw)
    chapters = detect_chapters(canonical)
    chunks = chunk_text(canonical, config, [chapter.char_start for chapter in chapters])
    return ProcessedDocument(canonical, chapters, chunks, PIPELINE_VERSION)
