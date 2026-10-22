"""Sentence-aware chunking of the canonical text (FR-03).

Chunks are measured in characters, not LLM tokens, because speech engines work on text length.
Rules, in priority order:

  1. A chunk is a slice of the canonical text: ``text[char_start:char_end] == chunk.text``.
  2. The first chunk is short but always holds real speech: it keeps adding units (a heading counts
     as a unit) until it reaches ``first_short_chars``, and stays within ``first_max_chars``.
  3. Chunk sizes ramp up at the start of the document: a chunk may be at most ``ramp_factor`` times
     longer than the one before it, until ``max_chars``. Synthesis of chunk N+1 then finishes while
     chunk N is still playing (a 1,000-character chunk straight after a 3-second one would leave a
     gap). After that the ramp is over. Resuming mid-book needs the same care; the TTS scheduler
     handles it by synthesizing from the resume sentence first (it can use ``sentence_spans``).
  4. Chunks close early at a paragraph end once they reach 60% of their cap (at most
     ``min_chars``), so seams fall where a narrator would pause.
  5. A chunk never ends inside an open quotation when that can be avoided.
  6. A chunk never spans a chapter start.
  7. No chunk exceeds ``hard_max_chars``; oversized sentences are split at clause breaks. A single
     sentence longer than the ramp cap is still kept whole, up to that limit.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from app.normalize.segment import paragraph_spans, sentence_spans, split_oversized


@dataclass(frozen=True)
class ChunkConfig:
    first_short_chars: int = 80  # the first chunk keeps growing until it has this many characters
    first_max_chars: int = 300  # ...but never beyond this
    min_chars: int = 600
    max_chars: int = 1000
    hard_max_chars: int = 1500
    # Each chunk may be at most this many times longer than the last. It should stay below
    # 1 / real-time-factor of the TTS engine (RTF 0.5 means 2.0); the Sprint 0 spike measures it.
    ramp_factor: float = 2.0

    def __post_init__(self) -> None:
        if not 0 < self.min_chars <= self.max_chars <= self.hard_max_chars:
            raise ValueError("expected 0 < min_chars <= max_chars <= hard_max_chars")
        if self.ramp_factor < 1:
            raise ValueError("ramp_factor must be at least 1")

    def cap_after(self, previous_length: int) -> int:
        """Largest size the next chunk may aim for, given the length of the previous chunk."""
        return min(
            self.max_chars, max(self.first_short_chars, int(previous_length * self.ramp_factor))
        )


DEFAULT_CHUNK_CONFIG = ChunkConfig()


@dataclass(frozen=True)
class Chunk:
    index: int
    char_start: int
    char_end: int
    text: str
    text_hash: str


@dataclass(frozen=True)
class _Unit:
    """A sentence, or a piece of an oversized sentence."""

    start: int
    end: int
    para_end: bool  # last unit of its paragraph
    quote_open: bool  # a quotation is still open after this unit


def chunk_text(
    text: str,
    config: ChunkConfig = DEFAULT_CHUNK_CONFIG,
    chapter_starts: Iterable[int] = (),
) -> list[Chunk]:
    units = _build_units(text, config)
    if not units:
        return []
    starts = sorted(set(chapter_starts))

    def chapter_of(unit: _Unit) -> int:
        return bisect_right(starts, unit.start)

    chunks: list[Chunk] = []
    steady = False  # once chunks reach full size the ramp is over, even after a short chapter tail
    i = 0
    while i < len(units):
        if chunks:
            previous = chunks[-1]
            cap = (
                config.max_chars
                if steady
                else config.cap_after(previous.char_end - previous.char_start)
            )
            steady = cap >= config.max_chars
            j = _fill(units, i, cap, min(config.min_chars, int(cap * 0.6)), chapter_of)
        else:
            j = _first_end(units, i, config, chapter_of)
        j = _avoid_open_quote(units, i, j, config, chapter_of)
        start, end = units[i].start, units[j - 1].end
        body = text[start:end]
        chunks.append(
            Chunk(len(chunks), start, end, body, hashlib.sha256(body.encode()).hexdigest())
        )
        i = j
    return chunks


def _build_units(text: str, config: ChunkConfig) -> list[_Unit]:
    units: list[_Unit] = []
    for paragraph in paragraph_spans(text):
        sentences = sentence_spans(text, paragraph)
        scanned = paragraph.start
        straight = 0  # count of straight double quotes so far in this paragraph
        curly = 0  # opening minus closing curly double quotes
        for k, sentence in enumerate(sentences):
            seen = text[scanned : sentence.end]
            scanned = sentence.end
            straight += seen.count('"')
            curly += seen.count("“") - seen.count("”")
            is_last = k == len(sentences) - 1
            open_after = not is_last and (straight % 2 == 1 or curly > 0)
            pieces = (
                split_oversized(text, sentence, config.hard_max_chars)
                if sentence.length > config.hard_max_chars
                else [sentence]
            )
            for p, piece in enumerate(pieces):
                last_piece = p == len(pieces) - 1
                units.append(
                    _Unit(piece.start, piece.end, is_last and last_piece, open_after and last_piece)
                )
    return units


def _first_end(
    units: Sequence[_Unit], i: int, config: ChunkConfig, chapter_of: Callable[[_Unit], int]
) -> int:
    first = units[i]
    j = i + 1
    while (
        j < len(units)
        and units[j - 1].end - first.start < config.first_short_chars
        and chapter_of(units[j]) == chapter_of(first)
        and units[j].end - first.start <= config.first_max_chars
    ):
        j += 1
    return j


def _fill(
    units: Sequence[_Unit],
    i: int,
    cap: int,
    close_at: int,
    chapter_of: Callable[[_Unit], int],
) -> int:
    """End index (exclusive) of the chunk that starts at unit `i`."""
    start = units[i].start
    chapter = chapter_of(units[i])
    j = i
    while j < len(units):
        unit = units[j]
        if j > i and (chapter_of(unit) != chapter or unit.end - start > cap):
            break
        j += 1
        if unit.para_end and unit.end - start >= close_at:
            break
    return j


def _avoid_open_quote(
    units: Sequence[_Unit], i: int, j: int, config: ChunkConfig, chapter_of: Callable[[_Unit], int]
) -> int:
    """Move the chunk end so it does not fall inside a quotation, if that is possible."""
    if j >= len(units) or not units[j - 1].quote_open:
        return j
    start = units[i].start
    chapter = chapter_of(units[i])
    k = j
    while (
        k < len(units)
        and units[k - 1].quote_open
        and chapter_of(units[k]) == chapter
        and units[k].end - start <= config.hard_max_chars
    ):
        k += 1
    if not units[k - 1].quote_open:
        return k
    for c in range(j - 1, i, -1):  # back up to an earlier closed boundary
        if not units[c - 1].quote_open and units[c - 1].end - start >= config.min_chars // 2:
            return c
    return j
