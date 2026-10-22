"""HTTP byte-range parsing for audio delivery (section 4.4).

Players ask for audio in ranges so they can seek and resume without downloading a whole chunk.
Only a single range is supported, which is all audio players send.
"""

from __future__ import annotations

import re

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeNotSatisfiable(ValueError):
    """The requested range lies outside the file (HTTP 416)."""


def parse_byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return the inclusive (start, end) to serve, or None to serve the whole file.

    A missing, malformed, multi-range or backwards range is ignored (the whole file is served),
    as RFC 9110 allows. A range that starts beyond the end raises RangeNotSatisfiable.
    """
    if not header:
        return None
    match = _RANGE.fullmatch(header.strip())
    if match is None:
        return None
    first, last = match.groups()
    if not first and not last:
        return None
    if not first:  # suffix range: the last N bytes
        length = int(last)
        if length == 0 or size == 0:
            raise RangeNotSatisfiable
        return max(size - length, 0), size - 1
    start = int(first)
    if last and int(last) < start:
        return None
    if start >= size:
        raise RangeNotSatisfiable
    end = min(int(last), size - 1) if last else size - 1
    return start, end
