"""Paragraph and sentence segmentation over the canonical text.

Everything here returns `Span`s (character offsets into the original string) instead of copies,
so chunks can point back into the canonical text exactly (ADR-011).
"""

from __future__ import annotations

import re
from typing import NamedTuple


class Span(NamedTuple):
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


_PARAGRAPH_SEPARATOR = re.compile(r"\n[ \t]*\n\s*")
# Sentence-final punctuation run plus any closing quotes or brackets: ."  ?!  …)
_TERMINATOR = re.compile(r"[.!?…]+[\"'”’)\]]*")
_CLAUSE_CHARS = ",;:—–)"

# Abbreviations after which a period does not end a sentence. Joining two sentences by mistake
# is harmless (a slightly longer chunk); splitting "Dr. Smith" would be audible.
_ABBREVIATIONS = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "mt",
        "ft",
        "vs",
        "fig",
        "vol",
        "cf",
        "gen",
        "col",
        "lt",
        "capt",
        "sgt",
        "rev",
        "hon",
        "approx",
        "dept",
        "est",
        "al",
        "e.g",
        "i.e",
        "ca",
        "ph.d",
        "a.m",
        "p.m",
    }  # fmt: skip
)


def trim(text: str, start: int, end: int) -> Span | None:
    """Shrink [start, end) to exclude surrounding whitespace; None when nothing is left."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return Span(start, end) if end > start else None


def paragraph_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    position = 0
    for match in _PARAGRAPH_SEPARATOR.finditer(text):
        span = trim(text, position, match.start())
        if span:
            spans.append(span)
        position = match.end()
    tail = trim(text, position, len(text))
    if tail:
        spans.append(tail)
    return spans


def sentence_spans(text: str, paragraph: Span) -> list[Span]:
    """Split one paragraph into sentences."""
    spans: list[Span] = []
    position = paragraph.start
    for match in _TERMINATOR.finditer(text, paragraph.start, paragraph.end):
        end = match.end()
        if end >= paragraph.end or not text[end].isspace():
            continue  # "3.14", "U.S.A", or the end of the paragraph
        following = end
        while following < paragraph.end and text[following].isspace():
            following += 1
        if following >= paragraph.end:
            break
        if text[following].islower():
            continue  # "...," he said.  or  "e.g. something"
        if _is_abbreviation(text, match, paragraph.start, following):
            continue
        sentence = trim(text, position, end)
        if sentence:
            spans.append(sentence)
        position = following
    tail = trim(text, position, paragraph.end)
    if tail:
        spans.append(tail)
    return spans


def _is_abbreviation(text: str, match: re.Match[str], lower: int, following: int) -> bool:
    punctuation = match.group()
    if punctuation.rstrip("\"'”’)]") != ".":
        return False  # "!" and "?" always end a sentence
    word_match = re.search(
        r"([A-Za-z][A-Za-z.]*)$", text[max(lower, match.start() - 20) : match.start()]
    )
    if not word_match:
        return False
    word = word_match.group(1)
    lowered = word.lower().rstrip(".")
    if lowered in _ABBREVIATIONS:
        return True
    if len(word) == 1 and word.isupper():
        return True  # an initial: "J. K. Rowling"
    if "." in word and all(len(part) == 1 for part in word.split(".")):
        return True  # a dotted initialism: "U.S. Army"
    return lowered == "no" and text[following].isdigit()  # "No. 5"


def split_oversized(text: str, span: Span, limit: int) -> list[Span]:
    """Cut a span longer than `limit` into pieces, preferring clause punctuation, then spaces."""
    pieces: list[Span] = []
    start = span.start
    while span.end - start > limit:
        cut = _best_cut(text, start, start + limit, floor=start + max(1, limit // 3))
        piece = trim(text, start, cut)
        if piece:
            pieces.append(piece)
        start = cut
        while start < span.end and text[start].isspace():
            start += 1
    tail = trim(text, start, span.end)
    if tail:
        pieces.append(tail)
    return pieces


def _best_cut(text: str, start: int, window_end: int, floor: int) -> int:
    for i in range(window_end - 1, floor - 1, -1):
        if text[i] in _CLAUSE_CHARS and text[i + 1].isspace():
            return i + 1
    for i in range(window_end, floor - 1, -1):
        if text[i].isspace():
            return i
    return window_end  # an unbroken run such as a long URL: cut hard
