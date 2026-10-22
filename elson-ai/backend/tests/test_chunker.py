import random

import pytest

from app.normalize.chunker import DEFAULT_CHUNK_CONFIG, ChunkConfig, chunk_text

SENTENCES = [
    "The old lighthouse stood alone on the cliff.",
    "Waves broke against the rocks below.",
    "Nobody had climbed its stairs in years.",
    'Mara pushed the door open and whispered, "Is anyone here?"',
    "Dust drifted through the pale light.",
    "She counted the steps as she climbed, one hundred and twelve in all.",
]


def make_text(paragraphs: int, sentences_per_paragraph: int, seed: int = 1) -> str:
    rng = random.Random(seed)
    return "\n\n".join(
        " ".join(rng.choice(SENTENCES) for _ in range(sentences_per_paragraph))
        for _ in range(paragraphs)
    )


def squash(text: str) -> str:
    return "".join(text.split())


def check_invariants(text: str, chunks) -> None:
    previous_end = 0
    for position, chunk in enumerate(chunks):
        assert chunk.index == position
        assert text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.char_start >= previous_end
        assert chunk.text == chunk.text.strip()
        previous_end = chunk.char_end
    # Every non-whitespace character lands in exactly one chunk, in order.
    assert squash("".join(c.text for c in chunks)) == squash(text)


def test_empty_text_gives_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("\n\n  \n") == []


def test_a_short_text_is_one_chunk():
    chunks = chunk_text("Just one short sentence.")
    assert [c.text for c in chunks] == ["Just one short sentence."]
    assert chunks[0].char_start == 0


def test_chunks_are_exact_slices_that_cover_the_text():
    for seed in range(5):
        text = make_text(paragraphs=30, sentences_per_paragraph=6, seed=seed)
        check_invariants(text, chunk_text(text))


def test_chunks_are_deterministic_and_hashed_by_content():
    text = make_text(10, 5)
    first, second = chunk_text(text), chunk_text(text)
    assert first == second
    assert len({c.text_hash for c in first}) == len({c.text for c in first})
    assert all(len(c.text_hash) == 64 for c in first)


def test_first_chunk_is_short_but_holds_real_speech():
    text = "Chapter 1\n\nThe Storm\n\n" + make_text(8, 5)
    first = chunk_text(text)[0]
    config = DEFAULT_CHUNK_CONFIG
    assert len(first.text) >= config.first_short_chars
    assert len(first.text) <= config.first_max_chars
    assert first.text.startswith("Chapter 1")


def test_a_long_first_sentence_stays_whole_in_the_first_chunk():
    long_sentence = "This sentence just keeps going " + "and going " * 20 + "until it stops."
    chunks = chunk_text(long_sentence + " Next one.")
    assert chunks[0].text.startswith(long_sentence)


def test_chunk_sizes_ramp_up_without_jumping_more_than_the_ramp_factor():
    text = make_text(40, 6)
    config = DEFAULT_CHUNK_CONFIG
    chunks = chunk_text(text, config)
    sizes = [len(c.text) for c in chunks]
    assert sizes[0] < sizes[3] <= config.max_chars  # it does ramp
    for previous, current in zip(sizes, sizes[1:-1], strict=False):
        if current >= config.max_chars * 0.9:
            break  # steady state reached
        # one sentence of slack: a chunk may overshoot its cap by at most one unit
        assert current <= previous * config.ramp_factor + 80


def test_no_chunk_exceeds_the_hard_limit_even_for_one_endless_sentence():
    config = DEFAULT_CHUNK_CONFIG
    endless = "word " * 2000  # no punctuation at all
    chunks = chunk_text(endless, config)
    assert all(len(c.text) <= config.hard_max_chars for c in chunks)
    assert squash("".join(c.text for c in chunks)) == squash(endless)


def test_no_chunk_exceeds_the_hard_limit_for_an_unbroken_string():
    chunks = chunk_text("x" * 10_000)
    assert all(len(c.text) <= DEFAULT_CHUNK_CONFIG.hard_max_chars for c in chunks)
    assert sum(len(c.text) for c in chunks) == 10_000


def test_chunks_close_at_paragraph_ends_once_they_are_big_enough():
    # ramp_factor is huge so the startup ramp is out of the way and only the paragraph rule acts.
    config = ChunkConfig(
        first_short_chars=20, first_max_chars=60, min_chars=100, max_chars=400, ramp_factor=1000
    )
    text = make_text(20, 3)
    chunks = chunk_text(text, config)
    assert len(chunks) > 5
    for chunk in chunks[1:-1]:  # the first chunk is sized by its own rule, the last by the end
        assert text[chunk.char_end : chunk.char_end + 2] == "\n\n"


def test_during_the_startup_ramp_a_chunk_may_end_mid_paragraph():
    config = ChunkConfig(first_short_chars=20, first_max_chars=60, min_chars=100, max_chars=400)
    text = make_text(20, 3)
    chunks = chunk_text(text, config)
    assert any(text[c.char_end : c.char_end + 2] != "\n\n" for c in chunks[:5])


def test_a_chunk_never_ends_inside_a_quotation():
    quote = '"' + " ".join(["One two three four five."] * 12) + '"'
    text = f"He began to speak. {quote} Then he stopped. " + make_text(3, 3)
    config = ChunkConfig(
        first_short_chars=20, first_max_chars=60, min_chars=80, max_chars=200, hard_max_chars=600
    )
    chunks = chunk_text(text, config)
    check_invariants(text, chunks)
    assert all(c.text.count('"') % 2 == 0 for c in chunks)


def test_curly_quotes_are_respected_too():
    quote = "“" + " ".join(["Alpha beta gamma delta."] * 12) + "”"
    text = f"She answered. {quote} Silence followed."
    config = ChunkConfig(
        first_short_chars=20, first_max_chars=40, min_chars=60, max_chars=150, hard_max_chars=500
    )
    chunks = chunk_text(text, config)
    assert all(c.text.count("“") == c.text.count("”") for c in chunks)


def test_a_chunk_never_spans_a_chapter_start():
    text = make_text(10, 4) + "\n\nChapter 2\n\n" + make_text(10, 4, seed=9)
    boundary = text.index("Chapter 2")
    chunks = chunk_text(text, chapter_starts=[boundary])
    check_invariants(text, chunks)
    assert not any(c.char_start < boundary < c.char_end for c in chunks)
    assert any(c.char_start == boundary for c in chunks)


def test_a_paragraph_break_inside_a_chunk_is_preserved():
    chunks = chunk_text("First paragraph here.\n\nSecond paragraph here.")
    assert chunks[0].text == "First paragraph here.\n\nSecond paragraph here."


def test_config_validation():
    with pytest.raises(ValueError):
        ChunkConfig(min_chars=900, max_chars=800)
    with pytest.raises(ValueError):
        ChunkConfig(max_chars=2000, hard_max_chars=1500)
    with pytest.raises(ValueError):
        ChunkConfig(ramp_factor=0.5)
