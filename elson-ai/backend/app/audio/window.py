"""The rolling window: which chunks to have audio for, ahead of the listener (ADR-008).

Generating a whole book up front wastes money on audio nobody plays. Instead only about ten
minutes ahead of the playhead is kept ready. The first few chunks of a window are urgent: they go
to the high-priority queue so playback starts or resumes quickly.

This is a pure function of the chunk list and a position, so the same code serves the API, the
background worker and the tests.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from app.normalize.chunker import Chunk
from app.tts.base import estimate_duration_ms

DEFAULT_WINDOW_MS = 10 * 60 * 1000
URGENT_COUNT = 3


@dataclass(frozen=True)
class WindowItem:
    index: int
    urgent: bool


def chunk_index_at(chunks: Sequence[Chunk], char_offset: int) -> int | None:
    """The chunk holding `char_offset`; the next one when it falls in the gap between chunks.

    None when the offset is at or past the end of the last chunk (nothing left to play).
    """
    if not chunks or char_offset >= chunks[-1].char_end:
        return None
    index = max(bisect_right([chunk.char_start for chunk in chunks], char_offset) - 1, 0)
    if char_offset >= chunks[index].char_end:
        index += 1
    return index


def plan_window(
    chunks: Sequence[Chunk],
    playhead_offset: int,
    *,
    window_ms: int = DEFAULT_WINDOW_MS,
    speed: float = 1.0,
    urgent_count: int = URGENT_COUNT,
) -> list[WindowItem]:
    """Chunks to have ready from the playhead on, in playing order.

    The window ends after the chunk that takes the total estimated speaking time to `window_ms`,
    and always holds at least one chunk while anything is left to play.
    """
    start = chunk_index_at(chunks, playhead_offset)
    if start is None:
        return []
    items: list[WindowItem] = []
    total_ms = 0
    for index in range(start, len(chunks)):
        items.append(WindowItem(index, urgent=len(items) < urgent_count))
        total_ms += estimate_duration_ms(chunks[index].text, speed)
        if total_ms >= window_ms:
            break
    return items
