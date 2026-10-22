"""Chapter detection over the canonical text, used for chapter navigation (FR-05)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.normalize.segment import paragraph_spans

_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    "sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    "hundred"
)
_ROMAN = r"(?=[ivxlcdm])m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"
_NUMBERED = re.compile(
    rf"^(?:chapter|part|book|section)\s+(?:\d{{1,4}}|{_ROMAN}|(?:{_NUMBER_WORDS})(?:[\s-](?:{_NUMBER_WORDS}))*)\b",
    re.IGNORECASE,
)
_STANDALONE = re.compile(
    r"^(?:prologue|epilogue|preface|foreword|introduction|afterword|acknowledg(?:e)?ments"
    r"|appendix(?:\s+[a-z0-9]+)?)\.?$",
    re.IGNORECASE,
)

_MAX_HEADING_CHARS = 100
_MAX_SUBTITLE_CHARS = 60
# Headings closer together than this are a table of contents, not chapters.
_MIN_CHAPTER_CHARS = 200
# Text before the first heading becomes its own chapter only when it is this substantial.
_MIN_FRONT_MATTER_CHARS = 200
_SENTENCE_END = (".", "!", "?")


@dataclass(frozen=True)
class Chapter:
    index: int
    title: str
    char_start: int
    char_end: int


def detect_chapters(text: str) -> list[Chapter]:
    """Find chapter headings. Returns an empty list when the text has none."""
    paragraphs = paragraph_spans(text)
    found: list[tuple[int, str]] = []
    k = 0
    while k < len(paragraphs):
        span = paragraphs[k]
        match = _match_heading(text[span.start : span.end])
        if match is None:
            k += 1
            continue
        title, needs_subtitle = match
        if needs_subtitle and k + 1 < len(paragraphs):
            following = paragraphs[k + 1]
            subtitle = text[following.start : following.end]
            if _is_subtitle(subtitle) and _match_heading(subtitle) is None:
                title = f"{title}: {subtitle}"
                k += 1
        found.append((span.start, title))
        k += 1

    found = _drop_table_of_contents(found, len(text))
    if not found:
        return []

    chapters: list[tuple[int, str]] = []
    first_start = found[0][0]
    if len(text[:first_start].strip()) >= _MIN_FRONT_MATTER_CHARS:
        chapters.append((0, "Beginning"))
    chapters.extend(found)

    return [
        Chapter(
            index=i,
            title=title,
            char_start=start,
            char_end=chapters[i + 1][0] if i + 1 < len(chapters) else len(text),
        )
        for i, (start, title) in enumerate(chapters)
    ]


def _match_heading(paragraph: str) -> tuple[str, bool] | None:
    """Return (title, needs_subtitle) if `paragraph` is a heading, else None."""
    lines = [line.strip() for line in paragraph.split("\n")]
    if len(lines) > 2 or len(paragraph) > _MAX_HEADING_CHARS:
        return None
    first = lines[0]
    numbered = _NUMBERED.match(first)
    if not (numbered or _STANDALONE.match(first)):
        return None
    if first.endswith(_SENTENCE_END) and len(first.split()) > 6:
        return None  # a sentence that happens to start with "Chapter one ..."
    title = " ".join(first.split())
    if len(lines) == 2:
        if not _is_subtitle(lines[1]):
            return None
        return f"{title}: {lines[1]}", False
    # "Chapter 7" alone: a following short line is probably its title.
    return title, bool(numbered and numbered.end() == len(first.rstrip(" .:")))


def _is_subtitle(text: str) -> bool:
    return (
        0 < len(text) <= _MAX_SUBTITLE_CHARS
        and "\n" not in text
        and not text.endswith(_SENTENCE_END)
    )


def _drop_table_of_contents(
    found: list[tuple[int, str]], text_length: int
) -> list[tuple[int, str]]:
    kept = []
    for i, (start, title) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else text_length
        if i + 1 < len(found) and end - start < _MIN_CHAPTER_CHARS:
            continue
        kept.append((start, title))
    return kept
