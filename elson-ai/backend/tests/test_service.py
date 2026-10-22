from datetime import UTC, datetime, timedelta

import pytest

from app.config import PIPELINE_VERSION, Settings
from app.errors import AppError
from app.service import DocumentService
from app.store import InMemoryRepository

BODY = "The rain kept falling over the quiet town. " * 15
STORY = f"Chapter 1\n\nThe Storm\n\n{BODY}\n\n{BODY}\n\nChapter 2\n\n{BODY}\n\n{BODY}"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def service() -> DocumentService:
    return DocumentService(InMemoryRepository(), Settings(max_upload_bytes=100_000), Clock())


@pytest.fixture
def document(service):
    return service.create_document("alice", "story.txt", STORY.encode())


def code_of(call) -> str:
    with pytest.raises(AppError) as error:
        call()
    return error.value.code


def test_create_document_runs_the_pipeline(service, document):
    assert document.id.startswith("doc_")
    assert document.title == "story"
    assert document.source_kind == "txt"
    assert document.pipeline_version == PIPELINE_VERSION
    assert [c.title for c in document.chapters] == ["Chapter 1: The Storm", "Chapter 2"]
    assert document.chunks
    assert service.get_document("alice", document.id) is document


def test_rejects_empty_oversized_and_unreadable_files(service):
    assert code_of(lambda: service.create_document("alice", "a.txt", b"")) == "EMPTY_DOCUMENT"
    assert (
        code_of(lambda: service.create_document("alice", "a.txt", b"x" * 100_001))
        == "FILE_TOO_LARGE"
    )
    assert (
        code_of(lambda: service.create_document("alice", "a.txt", b"\n\n* * *\n  \n"))
        == "EMPTY_DOCUMENT"
    )
    assert (
        code_of(lambda: service.create_document("alice", "a.pdf", b"%PDF-1.4"))
        == "NOT_YET_SUPPORTED"
    )


def test_the_size_limit_message_names_the_limit(service):
    with pytest.raises(AppError) as error:
        service.create_document("alice", "a.txt", b"x" * 100_001)
    assert error.value.status_code == 413
    assert "megabytes" in error.value.message


def test_a_user_cannot_see_or_change_another_users_documents(service, document):
    assert code_of(lambda: service.get_document("bob", document.id)) == "DOCUMENT_NOT_FOUND"
    assert code_of(lambda: service.delete_document("bob", document.id)) == "DOCUMENT_NOT_FOUND"
    assert code_of(lambda: service.save_progress("bob", document.id, 5)) == "DOCUMENT_NOT_FOUND"
    assert service.list_documents("bob") == []
    assert service.list_documents("alice") == [document]


def test_documents_are_listed_newest_first(service, document):
    newer = service.create_document("alice", "newer.txt", STORY.encode())
    assert [d.id for d in service.list_documents("alice")] == [newer.id, document.id]


def test_delete_removes_the_document_and_everything_derived_from_it(service, document):
    service.save_progress("alice", document.id, 10, "phone")
    service.add_bookmark("alice", document.id, 20, "Here")
    service.delete_document("alice", document.id)
    assert code_of(lambda: service.get_document("alice", document.id)) == "DOCUMENT_NOT_FOUND"
    assert code_of(lambda: service.delete_document("alice", document.id)) == "DOCUMENT_NOT_FOUND"


def test_chunk_paging(service, document):
    total = len(document.chunks)
    page, following = service.get_chunks("alice", document.id, 0, 3)
    assert [c.index for c in page] == [0, 1, 2]
    assert following == 3
    last, following = service.get_chunks("alice", document.id, total - 1, 5)
    assert [c.index for c in last] == [total - 1]
    assert following is None
    beyond, following = service.get_chunks("alice", document.id, total + 10, 5)
    assert beyond == [] and following is None


@pytest.mark.parametrize(("start", "limit"), [(-1, 10), (0, 0), (0, 201)])
def test_chunk_paging_rejects_bad_arguments(service, document, start, limit):
    assert (
        code_of(lambda: service.get_chunks("alice", document.id, start, limit)) == "INVALID_REQUEST"
    )


def test_locate_maps_an_offset_to_its_chunk_and_chapter(service, document):
    chunk = document.chunks[2]
    inside = service.locate(document, chunk.char_start + 3)
    assert inside.chunk_index == 2
    second_chapter = document.chapters[1]
    assert service.locate(document, second_chapter.char_start).chapter_index == 1
    assert service.locate(document, 0).chapter_index == 0


def test_locate_resolves_whitespace_between_chunks_to_the_next_chunk(service, document):
    first = document.chunks[0]
    assert document.chunks[1].char_start > first.char_end  # there is a gap
    assert service.locate(document, first.char_end).chunk_index == 1


def test_locate_at_the_very_end_gives_the_last_chunk(service, document):
    position = service.locate(document, len(document.text))
    assert position.chunk_index == len(document.chunks) - 1


def test_progress_round_trip(service, document):
    assert service.get_progress("alice", document.id) is None
    saved = service.save_progress("alice", document.id, 500, "phone")
    progress, position = service.get_progress("alice", document.id)
    assert progress == saved
    assert progress.char_offset == 500
    assert position.chunk_index is not None


@pytest.mark.parametrize("offset", [-1, 10**9])
def test_progress_outside_the_document_is_rejected(service, document, offset):
    assert (
        code_of(lambda: service.save_progress("alice", document.id, offset)) == "INVALID_POSITION"
    )


def test_overwriting_progress_from_another_device_keeps_the_old_position(service, document):
    service.save_progress("alice", document.id, 500, "phone")
    service.save_progress("alice", document.id, 100, "laptop")
    bookmarks = service.list_bookmarks("alice", document.id)
    assert [(b.char_offset, b.label, b.automatic) for b in bookmarks] == [
        (500, "Previous position", True)
    ]
    assert service.get_progress("alice", document.id)[0].char_offset == 100


def test_progress_from_the_same_device_creates_no_bookmark(service, document):
    service.save_progress("alice", document.id, 100, "phone")
    service.save_progress("alice", document.id, 300, "phone")
    service.save_progress("alice", document.id, 300, "laptop")  # same position: nothing to lose
    assert service.list_bookmarks("alice", document.id) == []


def test_bookmarks_are_sorted_by_position_and_validated(service, document):
    service.add_bookmark("alice", document.id, 900, "  Later ")
    service.add_bookmark("alice", document.id, 100)
    bookmarks = service.list_bookmarks("alice", document.id)
    assert [(b.char_offset, b.label, b.automatic) for b in bookmarks] == [
        (100, "", False),
        (900, "Later", False),
    ]
    assert code_of(lambda: service.add_bookmark("alice", document.id, -5)) == "INVALID_POSITION"
    assert (
        code_of(lambda: service.add_bookmark("alice", document.id, 5, "x" * 201))
        == "INVALID_REQUEST"
    )
