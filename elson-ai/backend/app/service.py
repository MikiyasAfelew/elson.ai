"""Application logic. The HTTP layer (main.py) is a thin wrapper around this class."""

from __future__ import annotations

import uuid
from bisect import bisect_right
from collections.abc import Callable
from datetime import UTC, datetime

from app.config import PIPELINE_VERSION, Settings
from app.errors import AppError
from app.ingestion import extract_text, safe_filename
from app.models import Bookmark, Document, Position, Progress
from app.normalize.chunker import Chunk
from app.pipeline import process_text
from app.store import InMemoryRepository

MAX_PAGE_SIZE = 200
MAX_LABEL_CHARS = 200


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class DocumentService:
    def __init__(
        self,
        repository: InMemoryRepository,
        settings: Settings,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._repo = repository
        self._settings = settings
        self._clock = clock

    # ---- documents -------------------------------------------------------------------------

    def create_document(self, user_id: str, filename: str | None, data: bytes) -> Document:
        if len(data) > self._settings.max_upload_bytes:
            limit_mb = self._settings.max_upload_bytes // (1024 * 1024)
            raise AppError(
                "FILE_TOO_LARGE",
                f"This file is too large. The limit is {limit_mb} megabytes. "
                "Try splitting it into smaller parts.",
                status_code=413,
            )
        if not data:
            raise AppError("EMPTY_DOCUMENT", "This file is empty. Try a different file.", 422)

        extracted = extract_text(filename, data)
        processed = process_text(extracted.text)
        if not processed.chunks:
            raise AppError(
                "EMPTY_DOCUMENT",
                "We couldn't find any readable text in this file. Try a different file.",
                status_code=422,
            )
        document = Document(
            id=_new_id("doc"),
            user_id=user_id,
            title=extracted.title,
            source_kind=extracted.kind,
            filename=safe_filename(filename),
            created_at=self._clock(),
            text=processed.text,
            chapters=processed.chapters,
            chunks=processed.chunks,
            pipeline_version=processed.pipeline_version,
        )
        self._repo.add_document(document)
        return document

    def get_document(self, user_id: str, document_id: str) -> Document:
        document = self._repo.get_document(user_id, document_id)
        if document is None:
            raise AppError("DOCUMENT_NOT_FOUND", "We couldn't find that document.", 404)
        return document

    def list_documents(self, user_id: str) -> list[Document]:
        return self._repo.list_documents(user_id)

    def delete_document(self, user_id: str, document_id: str) -> None:
        if not self._repo.delete_document(user_id, document_id):
            raise AppError("DOCUMENT_NOT_FOUND", "We couldn't find that document.", 404)

    def get_chunks(
        self, user_id: str, document_id: str, start: int = 0, limit: int = 20
    ) -> tuple[list[Chunk], int | None]:
        """A page of chunks, and the `start` of the next page (None at the end)."""
        if start < 0 or not 1 <= limit <= MAX_PAGE_SIZE:
            raise AppError(
                "INVALID_REQUEST",
                f"Ask for between 1 and {MAX_PAGE_SIZE} chunks, starting at zero or later.",
                422,
            )
        document = self.get_document(user_id, document_id)
        page = document.chunks[start : start + limit]
        following = start + limit
        return page, (following if following < len(document.chunks) else None)

    # ---- positions -------------------------------------------------------------------------

    def locate(self, document: Document, char_offset: int) -> Position:
        """Resolve a character offset to the chunk and chapter that contain it."""
        chunk_index: int | None = None
        if document.chunks:
            starts = [chunk.char_start for chunk in document.chunks]
            chunk_index = max(bisect_right(starts, char_offset) - 1, 0)
            in_gap = char_offset >= document.chunks[chunk_index].char_end
            if in_gap and chunk_index + 1 < len(document.chunks):
                chunk_index += 1  # whitespace between chunks: continue with the next one
        chapter_index: int | None = None
        if document.chapters:
            chapter_starts = [chapter.char_start for chapter in document.chapters]
            chapter_index = max(bisect_right(chapter_starts, char_offset) - 1, 0)
        return Position(char_offset, chunk_index, chapter_index)

    def _check_offset(self, document: Document, char_offset: int) -> None:
        if not 0 <= char_offset <= len(document.text):
            raise AppError(
                "INVALID_POSITION",
                "That position is outside the document. Try going back to the start.",
                422,
            )

    def save_progress(
        self,
        user_id: str,
        document_id: str,
        char_offset: int,
        device_id: str | None = None,
    ) -> Progress:
        """Save the listening position. The latest write wins.

        When a different device overwrites a position, the old one is kept as an automatic
        bookmark so nothing is lost (ADR-011).
        """
        document = self.get_document(user_id, document_id)
        self._check_offset(document, char_offset)
        previous = self._repo.get_progress(user_id, document_id)
        if (
            previous is not None
            and previous.device_id != device_id
            and previous.char_offset != char_offset
        ):
            self._repo.add_bookmark(
                user_id,
                document_id,
                Bookmark(
                    _new_id("bm"), previous.char_offset, "Previous position", True, self._clock()
                ),
            )
        progress = Progress(char_offset, PIPELINE_VERSION, device_id, self._clock())
        self._repo.set_progress(user_id, document_id, progress)
        return progress

    def get_progress(self, user_id: str, document_id: str) -> tuple[Progress, Position] | None:
        document = self.get_document(user_id, document_id)
        progress = self._repo.get_progress(user_id, document_id)
        if progress is None:
            return None
        return progress, self.locate(document, progress.char_offset)

    # ---- bookmarks -------------------------------------------------------------------------

    def add_bookmark(
        self, user_id: str, document_id: str, char_offset: int, label: str = ""
    ) -> Bookmark:
        document = self.get_document(user_id, document_id)
        self._check_offset(document, char_offset)
        label = label.strip()
        if len(label) > MAX_LABEL_CHARS:
            raise AppError(
                "INVALID_REQUEST",
                f"Bookmark names can be up to {MAX_LABEL_CHARS} characters long.",
                422,
            )
        bookmark = Bookmark(_new_id("bm"), char_offset, label, False, self._clock())
        self._repo.add_bookmark(user_id, document_id, bookmark)
        return bookmark

    def list_bookmarks(self, user_id: str, document_id: str) -> list[Bookmark]:
        self.get_document(user_id, document_id)
        return self._repo.list_bookmarks(user_id, document_id)
