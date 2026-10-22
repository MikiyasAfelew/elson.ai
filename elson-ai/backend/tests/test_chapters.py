from app.normalize.chapters import detect_chapters

BODY = "The rain kept falling over the quiet town. " * 12  # 500+ characters


def titles(text: str) -> list[str]:
    return [chapter.title for chapter in detect_chapters(text)]


def test_no_headings_gives_no_chapters():
    assert detect_chapters(BODY) == []
    assert detect_chapters("") == []


def test_detects_numbered_headings_in_several_styles():
    text = (
        f"Chapter 1\n\n{BODY}\n\nCHAPTER TWO\n\n{BODY}\n\nChapter IV\n\n{BODY}\n\nPart 3\n\n{BODY}"
    )
    assert titles(text) == ["Chapter 1", "CHAPTER TWO", "Chapter IV", "Part 3"]


def test_attaches_a_short_following_line_as_the_title():
    text = f"Chapter 7\n\nThe Storm\n\n{BODY}\n\nChapter 8\n\n{BODY}"
    assert titles(text) == ["Chapter 7: The Storm", "Chapter 8"]


def test_keeps_an_inline_title():
    text = f"Chapter 12. The End\n\n{BODY}"
    assert titles(text) == ["Chapter 12. The End"]


def test_detects_standalone_headings():
    text = f"Prologue\n\n{BODY}\n\nEpilogue\n\n{BODY}"
    assert titles(text) == ["Prologue", "Epilogue"]


def test_ignores_sentences_that_merely_start_with_a_heading_word():
    text = (
        "Part of the problem was simple.\n\n"
        "Chapter one of the book was long and tedious, he said.\n\n"
        "Book your tickets early.\n\n"
        f"{BODY}"
    )
    assert detect_chapters(text) == []


def test_a_table_of_contents_is_not_mistaken_for_chapters():
    contents = "Chapter 1\n\nChapter 2\n\nChapter 3"
    text = f"{contents}\n\nChapter 1\n\n{BODY}\n\nChapter 2\n\n{BODY}\n\nChapter 3\n\n{BODY}"
    chapters = detect_chapters(text)
    assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert chapters[0].char_start > len(contents)


def test_substantial_text_before_the_first_heading_becomes_a_beginning_chapter():
    text = f"{BODY}\n\nChapter 1\n\n{BODY}"
    chapters = detect_chapters(text)
    assert [c.title for c in chapters] == ["Beginning", "Chapter 1"]
    assert chapters[0].char_start == 0


def test_a_title_page_before_the_first_heading_is_not_a_chapter():
    text = f"My Book\n\nBy Someone\n\nChapter 1\n\n{BODY}"
    assert titles(text) == ["Chapter 1"]


def test_chapters_are_contiguous_and_cover_the_rest_of_the_text():
    text = f"Chapter 1\n\n{BODY}\n\nChapter 2\n\n{BODY}\n\nChapter 3\n\n{BODY}"
    chapters = detect_chapters(text)
    assert [c.index for c in chapters] == [0, 1, 2]
    assert chapters[0].char_start == 0
    for current, following in zip(chapters, chapters[1:], strict=False):
        assert current.char_end == following.char_start
    assert chapters[-1].char_end == len(text)
    assert text[chapters[1].char_start :].startswith("Chapter 2")
