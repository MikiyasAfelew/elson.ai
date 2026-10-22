import textwrap

from app.config import PIPELINE_VERSION
from app.pipeline import process_text

STORY = (
    "The old lighthouse stood alone on the cliff. Waves broke against the rocks below. "
    'Mara pushed the door open and whispered, "Is anyone here?" Dust drifted through the '
    "pale light. She counted the steps as she climbed. "
) * 4


def build_book() -> str:
    chapter = "\n\n".join(textwrap.fill(STORY, 72) for _ in range(5))
    return f"CHAPTER ONE\n\nThe Climb\n\n{chapter}\n\nPage 14\n\n* * *\n\nChapter 2\n\n{chapter}"


def test_process_text_returns_canonical_text_chapters_and_chunks():
    document = process_text(build_book())
    assert document.pipeline_version == PIPELINE_VERSION
    assert [c.title for c in document.chapters] == ["CHAPTER ONE: The Climb", "Chapter 2"]
    assert document.chunks
    assert "Page 14" not in document.text
    assert "* * *" not in document.text
    assert "\n" not in document.text.replace("\n\n", "")  # wrapped lines were re-flowed


def test_chunk_offsets_point_into_the_canonical_text():
    document = process_text(build_book())
    for chunk in document.chunks:
        assert document.text[chunk.char_start : chunk.char_end] == chunk.text


def test_no_chunk_crosses_a_chapter_boundary():
    document = process_text(build_book())
    for chapter in document.chapters:
        assert not any(c.char_start < chapter.char_start < c.char_end for c in document.chunks)


def test_empty_input_gives_an_empty_document():
    document = process_text("   \n\n* * *\n")
    assert document.text == ""
    assert document.chunks == []
    assert document.chapters == []
