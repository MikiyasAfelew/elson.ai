"""In-memory repository.

Good enough for Sprint 1 and for tests. It is replaced by PostgreSQL and object storage in
Sprint 6; the service layer only talks to this interface, and every method is scoped by user id so
one user can never reach another user's documents.
"""

from __future__ import annotations

import threading

from app.models import Bookmark, Document, Progress


class InMemoryRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._documents: dict[str, dict[str, Document]] = {}
        self._progress: dict[tuple[str, str], Progress] = {}
        self._bookmarks: dict[tuple[str, str], list[Bookmark]] = {}

    def add_document(self, document: Document) -> None:
        with self._lock:
            self._documents.setdefault(document.user_id, {})[document.id] = document

    def get_document(self, user_id: str, document_id: str) -> Document | None:
        with self._lock:
            return self._documents.get(user_id, {}).get(document_id)

    def list_documents(self, user_id: str) -> list[Document]:
        with self._lock:
            documents = list(self._documents.get(user_id, {}).values())
        return sorted(documents, key=lambda d: d.created_at, reverse=True)

    def delete_document(self, user_id: str, document_id: str) -> bool:
        """Remove the document and everything derived from it."""
        with self._lock:
            removed = self._documents.get(user_id, {}).pop(document_id, None)
            self._progress.pop((user_id, document_id), None)
            self._bookmarks.pop((user_id, document_id), None)
            return removed is not None

    def get_progress(self, user_id: str, document_id: str) -> Progress | None:
        with self._lock:
            return self._progress.get((user_id, document_id))

    def set_progress(self, user_id: str, document_id: str, progress: Progress) -> None:
        with self._lock:
            self._progress[(user_id, document_id)] = progress

    def add_bookmark(self, user_id: str, document_id: str, bookmark: Bookmark) -> None:
        with self._lock:
            self._bookmarks.setdefault((user_id, document_id), []).append(bookmark)

    def list_bookmarks(self, user_id: str, document_id: str) -> list[Bookmark]:
        with self._lock:
            return sorted(
                self._bookmarks.get((user_id, document_id), []), key=lambda b: b.char_offset
            )
