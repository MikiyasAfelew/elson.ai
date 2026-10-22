"""Rule-based text cleaning (FR-02, ADR-005: rules before LLM).

`clean_text` turns raw extracted text into the *canonical text*: the single string that chunk
offsets, bookmarks and reading progress all point into. Paragraphs are separated by exactly one
blank line ("\\n\\n"); everything else is plain text.

What it does:
  * normalizes Unicode, line endings, odd spaces and invisible characters;
  * removes explicit page-number lines ("Page 12", "12 of 300", "- 12 -");
  * when the input has page breaks (form feeds, which the PDF parser will insert), removes running
    headers, footers and bare page numbers that repeat at page edges;
  * re-joins words hyphenated across line ends and re-flows hard-wrapped lines into paragraphs;
  * drops scene-break ornaments ("* * *") and numeric footnote markers ("[12]").

Known trade-offs (all deliberate, all covered by tests):
  * A real hyphenated compound split across two lines ("well-\\nknown") is joined as "wellknown".
  * Bare number lines in a plain .txt file are kept, because a chapter number looks the same as a
    page number. They are only removed at page edges when pages are known.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

PAGE_BREAK = "\f"

_INVISIBLE = str.maketrans("", "", "­​‌‍⁠﻿")
_SPACES = str.maketrans({ord(c): " " for c in "               　\t"})

_EXPLICIT_PAGE_NUMBER = re.compile(
    r"""^(?:
        (?:page|pg\.?|p\.)\s*\d{1,5}(?:\s*of\s*\d{1,5})?   # Page 12, Page 12 of 300
        |\d{1,5}\s*of\s*\d{1,5}                            # 12 of 300
        |[-–—]\s*\d{1,5}\s*[-–—]       # - 12 -
    )$""",
    re.IGNORECASE | re.VERBOSE,
)
_SCENE_BREAK = re.compile(r"^(?:[*\-_=~#•·]\s*){3,}$")
_FOOTNOTE_MARKER = re.compile(r"(?<=[A-Za-z.,;:!?\"”’)])\[\d{1,3}\]")
_HYPHEN_AT_END = re.compile(r"[^\W\d_]-$")

_MIN_PAGES_FOR_HEADERS = 3
_HEADER_REPEAT_SHARE = 0.4
_MAX_HEADER_CHARS = 80
# Pages with fewer non-blank lines than this are left alone: on a tiny page the "edge" lines are
# the content, and a body line that differs from the next page's only in a digit would be deleted.
_MIN_LINES_FOR_HEADER_DETECTION = 4
_SENTENCE_END = (".", "!", "?")

# A line break is a soft wrap (join) when the line is at least this share of the typical width.
_WRAP_FILL = 0.8
# Below this typical width the text is verse or short lines: keep the line breaks.
_MIN_WRAP_WIDTH = 40


def clean_text(raw: str) -> str:
    """Return the canonical text for `raw` (empty string when nothing readable remains)."""
    text = _normalize_chars(raw)
    pages = [[line.rstrip() for line in page.split("\n")] for page in text.split(PAGE_BREAK)]
    pages = _strip_running_headers(pages)

    lines = [line.strip() for page in pages for line in page]
    lines = [line for line in lines if not _EXPLICIT_PAGE_NUMBER.match(line)]
    lines = ["" if _SCENE_BREAK.match(line) else line for line in lines]
    lines = _dehyphenate(lines)

    paragraphs = (_tidy(p) for p in _unwrap(lines))
    return "\n\n".join(p for p in paragraphs if p)


def _normalize_chars(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", "\n").replace(" ", "\n\n")
    text = text.translate(_INVISIBLE).translate(_SPACES)
    return "".join(ch for ch in text if ch in "\n\f" or unicodedata.category(ch) != "Cc")


def _edge_key(line: str) -> str:
    """Compare lines ignoring case, spacing and digits, so "Page 4" and "Page 5" match."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line.strip().lower()))


def _edge_entries(page: list[str]) -> list[tuple[int, str]]:
    """(line index, key) for the lines at the top and bottom edge of a page."""
    nonblank = [i for i, line in enumerate(page) if line.strip()]
    if len(nonblank) < _MIN_LINES_FOR_HEADER_DETECTION:
        return []
    entries: list[tuple[int, str]] = []
    for position, index in enumerate(nonblank):
        from_top = position
        from_bottom = len(nonblank) - 1 - position
        if min(from_top, from_bottom) > 1:
            continue
        key = _edge_key(page[index])
        # Running headers are labels, not sentences: a line that ends like a sentence is body text.
        if not key or len(key) > _MAX_HEADER_CHARS or key.endswith(_SENTENCE_END):
            continue
        # Only the outermost line may be a bare page number; this protects a chapter number
        # that happens to sit one line in from the page edge.
        if key == "#" and min(from_top, from_bottom) != 0:
            continue
        entries.append((index, key))
    return entries


def _strip_running_headers(pages: list[list[str]]) -> list[list[str]]:
    if len(pages) < _MIN_PAGES_FOR_HEADERS:
        return pages
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({key for _, key in _edge_entries(page)})
    threshold = max(_MIN_PAGES_FOR_HEADERS, math.ceil(len(pages) * _HEADER_REPEAT_SHARE))
    repeated = {key for key, seen in counts.items() if seen >= threshold}
    if not repeated:
        return pages
    cleaned = []
    for page in pages:
        drop = {index for index, key in _edge_entries(page) if key in repeated}
        cleaned.append([line for i, line in enumerate(page) if i not in drop])
    return cleaned


def _dehyphenate(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        while (
            _HYPHEN_AT_END.search(line)
            and i + 1 < len(lines)
            and lines[i + 1]
            and lines[i + 1][0].islower()
        ):
            line = line[:-1] + lines[i + 1]
            i += 1
        out.append(line)
        i += 1
    return out


def _blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _typical_width(blocks: list[list[str]]) -> int:
    """Width the text was hard-wrapped at, from the non-final lines of multi-line blocks."""
    lengths = sorted(len(line) for block in blocks if len(block) > 1 for line in block[:-1])
    if not lengths:
        return 0
    return lengths[int(0.9 * (len(lengths) - 1))]


def _unwrap(lines: list[str]) -> list[str]:
    blocks = _blocks(lines)
    width = _typical_width(blocks)
    paragraphs: list[str] = []
    for block in blocks:
        if len(block) == 1:
            paragraphs.append(block[0])
        elif width < _MIN_WRAP_WIDTH:
            paragraphs.append("\n".join(block))
        else:
            current = block[0]
            for previous, line in zip(block, block[1:], strict=False):
                if len(previous) >= _WRAP_FILL * width:
                    current += " " + line
                else:
                    paragraphs.append(current)
                    current = line
            paragraphs.append(current)
    return paragraphs


def _tidy(paragraph: str) -> str:
    lines = (re.sub(r" {2,}", " ", line).strip() for line in paragraph.split("\n"))
    text = "\n".join(line for line in lines if line)
    return _FOOTNOTE_MARKER.sub("", text).strip()
