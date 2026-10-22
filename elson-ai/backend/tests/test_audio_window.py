from app.audio.window import URGENT_COUNT, chunk_index_at, plan_window
from app.normalize.chunker import Chunk

# 20 chunks of 150 characters (10 seconds of speech each), separated by a 2-character gap.
CHUNKS = [Chunk(i, i * 152, i * 152 + 150, "x" * 150, f"h{i}") for i in range(20)]


def indexes(items):
    return [item.index for item in items]


def test_an_offset_inside_a_chunk_finds_that_chunk():
    assert chunk_index_at(CHUNKS, 0) == 0
    assert chunk_index_at(CHUNKS, 152 * 3 + 40) == 3


def test_an_offset_in_the_gap_between_chunks_finds_the_next_one():
    assert chunk_index_at(CHUNKS, 150) == 1
    assert chunk_index_at(CHUNKS, 151) == 1


def test_an_offset_at_or_past_the_end_finds_nothing():
    assert chunk_index_at(CHUNKS, CHUNKS[-1].char_end) is None
    assert chunk_index_at(CHUNKS, 10**9) is None
    assert chunk_index_at([], 0) is None


def test_the_window_starts_at_the_playhead_and_runs_in_playing_order():
    items = plan_window(CHUNKS, 152 * 4, window_ms=40_000)
    assert indexes(items) == [4, 5, 6, 7]  # 4 chunks x 10 s reaches the 40 s window


def test_the_first_chunks_of_a_window_are_urgent():
    items = plan_window(CHUNKS, 0, window_ms=100_000)
    assert [item.urgent for item in items] == [True] * URGENT_COUNT + [False] * 7


def test_the_window_stops_at_the_end_of_the_document():
    assert indexes(plan_window(CHUNKS, 152 * 18, window_ms=10**9)) == [18, 19]


def test_a_window_always_holds_at_least_one_chunk():
    assert indexes(plan_window(CHUNKS, 0, window_ms=1)) == [0]


def test_faster_speech_needs_more_chunks_to_fill_the_same_window():
    normal = plan_window(CHUNKS, 0, window_ms=60_000, speed=1.0)
    fast = plan_window(CHUNKS, 0, window_ms=60_000, speed=2.0)
    assert len(fast) == 2 * len(normal)


def test_nothing_is_planned_once_the_document_is_finished():
    assert plan_window(CHUNKS, CHUNKS[-1].char_end) == []
