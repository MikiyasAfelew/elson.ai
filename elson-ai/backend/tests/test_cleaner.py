import textwrap

from app.normalize.cleaner import clean_text

PARAGRAPH = (
    "It was a bright cold day in April, and the clocks were striking thirteen. Winston Smith "
    "slipped quickly through the glass doors of Victory Mansions, though not quickly enough to "
    "prevent a swirl of gritty dust from entering along with him."
)


def test_empty_and_whitespace_only_input_gives_empty_text():
    assert clean_text("") == ""
    assert clean_text("  \n\n \t \n") == ""


def test_normalizes_line_endings_spaces_and_invisible_characters():
    raw = "Hello world\r\nsoft­hyphen zero​width\rtab\there"
    # Short lines keep their breaks, so the three input lines stay three lines.
    assert clean_text(raw) == "Hello world\nsofthyphen zerowidth\ntab here"


def test_composes_unicode_to_nfc():
    decomposed = "café"  # e + combining acute accent
    assert clean_text(decomposed) == "café"


def test_drops_control_characters():
    assert clean_text("abc\x07def\x00ghi") == "abcdefghi"


def test_removes_explicit_page_number_lines():
    raw = "First paragraph here.\n\nPage 12\n\n12 of 300\n\n- 12 -\n\np. 7\n\nSecond paragraph."
    assert clean_text(raw) == "First paragraph here.\n\nSecond paragraph."


def test_keeps_sentences_that_merely_start_like_a_page_number():
    raw = "Page 12 is missing from the book.\n\nIt was never found."
    assert clean_text(raw) == raw


def test_keeps_bare_numbers_in_plain_text_because_they_may_be_chapter_numbers():
    raw = "1\n\nThe Beginning\n\nOnce upon a time."
    assert clean_text(raw).startswith("1\n\nThe Beginning")


def body_lines(number: int) -> list[str]:
    return [
        f"This is line {line} of the text and it sits on page {number}." for line in range(1, 6)
    ]


def make_page(number: int, header: str = "MY BOOK TITLE") -> str:
    return f"{header}\n\n" + "\n".join(body_lines(number)) + f"\n\n{number}"


def test_removes_running_headers_footers_and_page_numbers_when_pages_are_known():
    cleaned = clean_text("\f".join(make_page(n) for n in range(1, 7)))
    assert cleaned.split("\n\n") == [" ".join(body_lines(n)) for n in range(1, 7)]


def test_does_not_strip_headers_when_there_are_too_few_pages():
    pages = "\f".join(make_page(n) for n in range(1, 3))
    assert "MY BOOK TITLE" in clean_text(pages)


def test_tiny_pages_are_never_emptied_by_header_detection():
    # Regression: the body line differs between pages only by a digit, so it once looked like a
    # repeating header and the whole document was deleted.
    pages = [f"MY BOOK TITLE\n\nBody text of page {n} is here.\n\n{n}" for n in range(1, 7)]
    cleaned = clean_text("\f".join(pages))
    for n in range(1, 7):
        assert f"Body text of page {n} is here." in cleaned


def test_a_body_line_that_ends_like_a_sentence_is_never_a_running_header():
    pages = []
    for n in range(1, 7):
        body = "\n".join(
            f"Filler line {k} of page {n} with enough words to wrap." for k in range(1, 5)
        )
        pages.append(f"MY BOOK TITLE\n\nAs I said before, this is page {n}.\n{body}\n\n{n}")
    cleaned = clean_text("\f".join(pages))
    assert "MY BOOK TITLE" not in cleaned
    assert "As I said before, this is page 4." in cleaned


def test_a_chapter_number_one_line_in_from_a_page_edge_is_kept():
    pages = [make_page(n, header="Running Head") for n in range(1, 6)]
    pages[2] = (
        "Running Head\n\n3\n\n" + "\n".join(body_lines(3)) + "\n\n3"
    )  # "3" is a chapter number
    cleaned = clean_text("\f".join(pages))
    assert "Running Head" not in cleaned
    assert "3" in cleaned.split("\n\n")


def test_joins_words_hyphenated_across_lines():
    assert clean_text("The exam-\nple works.") == "The example works."


def test_keeps_hyphen_when_next_line_is_not_lowercase_and_keeps_dashes():
    assert "Anglo-" in clean_text("Anglo-\nSaxon history")
    assert "wait--" in clean_text("But wait--\nwhat now")


def test_reflows_hard_wrapped_paragraphs():
    wrapped = textwrap.fill(PARAGRAPH, 70)
    assert "\n" in wrapped
    raw = f"{wrapped}\n\n{wrapped}"
    assert clean_text(raw) == f"{PARAGRAPH}\n\n{PARAGRAPH}"


def test_reflow_does_not_merge_a_paragraph_that_ends_exactly_at_the_wrap_width():
    first = textwrap.fill(PARAGRAPH, 70)
    second = textwrap.fill(PARAGRAPH.replace("bright", "dark"), 70)
    cleaned = clean_text(f"{first}\n\n{second}")
    assert cleaned.count("\n\n") == 1


def test_short_dialogue_lines_stay_separate_paragraphs():
    wrapped = textwrap.fill(PARAGRAPH, 70)
    raw = f'{wrapped}\n\n"Hello," she said.\n"Hi," he replied.\n"Where to?" she asked.'
    cleaned = clean_text(raw)
    assert cleaned.split("\n\n")[1:] == [
        '"Hello," she said.',
        '"Hi," he replied.',
        '"Where to?" she asked.',
    ]


def test_verse_and_short_lines_keep_their_line_breaks():
    raw = "Roses are red,\nViolets are blue,\nSugar is sweet,\nAnd so are you."
    assert clean_text(raw) == raw


def test_removes_scene_breaks_and_footnote_markers():
    raw = "He left the room.[12]\n\n* * *\n\n-----\n\nShe stayed behind."
    assert clean_text(raw) == "He left the room.\n\nShe stayed behind."


def test_collapses_repeated_spaces():
    assert clean_text("one   two    three") == "one two three"


def test_is_idempotent():
    wrapped = textwrap.fill(PARAGRAPH, 70)
    raw = f"CHAPTER ONE\n\n{wrapped}\n\nPage 3\n\n{wrapped}\n\n* * *\n\n{wrapped}"
    once = clean_text(raw)
    assert clean_text(once) == once
