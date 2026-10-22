import pytest

from app.audio.http import RangeNotSatisfiable, parse_byte_range


def test_no_header_means_the_whole_file():
    assert parse_byte_range(None, 1000) is None
    assert parse_byte_range("", 1000) is None


def test_an_explicit_range_is_inclusive():
    assert parse_byte_range("bytes=0-99", 1000) == (0, 99)
    assert parse_byte_range("bytes=200-299", 1000) == (200, 299)


def test_an_open_ended_range_runs_to_the_end():
    assert parse_byte_range("bytes=900-", 1000) == (900, 999)


def test_an_end_past_the_file_is_clamped():
    assert parse_byte_range("bytes=900-5000", 1000) == (900, 999)


def test_a_suffix_range_asks_for_the_last_bytes():
    assert parse_byte_range("bytes=-100", 1000) == (900, 999)
    assert parse_byte_range("bytes=-5000", 1000) == (0, 999)


def test_a_range_starting_past_the_end_is_not_satisfiable():
    with pytest.raises(RangeNotSatisfiable):
        parse_byte_range("bytes=1000-", 1000)
    with pytest.raises(RangeNotSatisfiable):
        parse_byte_range("bytes=-0", 1000)


def test_malformed_unsupported_or_backwards_ranges_are_ignored():
    for header in ("bytes=", "bytes=-", "items=0-5", "bytes=0-5,10-20", "bytes=abc", "bytes=50-10"):
        assert parse_byte_range(header, 1000) is None
