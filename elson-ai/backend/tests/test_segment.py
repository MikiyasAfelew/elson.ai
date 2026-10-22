from app.normalize.segment import Span, paragraph_spans, sentence_spans, split_oversized


def sentences(text: str) -> list[str]:
    return [text[s.start : s.end] for s in sentence_spans(text, Span(0, len(text)))]


def test_paragraph_spans_point_into_the_original_text():
    text = "First one.\n\nSecond one.\n\n\nThird one."
    assert [text[s.start : s.end] for s in paragraph_spans(text)] == [
        "First one.",
        "Second one.",
        "Third one.",
    ]


def test_paragraph_spans_of_empty_text():
    assert paragraph_spans("") == []
    assert paragraph_spans("\n\n  \n") == []


def test_splits_simple_sentences():
    assert sentences("It rained. We stayed in! Did you go? No.") == [
        "It rained.",
        "We stayed in!",
        "Did you go?",
        "No.",
    ]


def test_does_not_split_after_titles_and_initials():
    text = "Dr. Smith met Mrs. Brown and J. K. Rowling. They talked."
    assert sentences(text) == ["Dr. Smith met Mrs. Brown and J. K. Rowling.", "They talked."]


def test_does_not_split_decimals_or_dotted_initialisms():
    assert sentences("It cost 3.14 dollars. Fine.") == ["It cost 3.14 dollars.", "Fine."]
    assert sentences("The U.S. Army left. Then it rained.") == [
        "The U.S. Army left.",
        "Then it rained.",
    ]


def test_does_not_split_before_a_lowercase_continuation():
    assert sentences('"Go home." he said. Then he left.') == [
        '"Go home." he said.',
        "Then he left.",
    ]
    assert sentences("Use fruit, e.g. apples. Done.") == ["Use fruit, e.g. apples.", "Done."]


def test_keeps_closing_quotes_with_their_sentence():
    assert sentences('He said, "Stop." She stopped.') == ['He said, "Stop."', "She stopped."]
    assert sentences("She sighed… Then she left.") == ["She sighed…", "Then she left."]


def test_number_abbreviation_only_before_a_digit():
    assert sentences("See No. 5 for details.") == ["See No. 5 for details."]
    assert sentences("He said no. Then he left.") == ["He said no.", "Then he left."]


def test_sentence_spans_cover_the_text_without_overlap():
    text = "One. Two! Three? Four."
    spans = sentence_spans(text, Span(0, len(text)))
    assert all(a.end <= b.start for a, b in zip(spans, spans[1:], strict=False))
    assert "".join(text[s.start : s.end] for s in spans).replace(" ", "") == text.replace(" ", "")


def test_split_oversized_respects_the_limit_and_loses_nothing():
    text = ("word " * 120).strip()
    pieces = split_oversized(text, Span(0, len(text)), 100)
    assert all(piece.length <= 100 for piece in pieces)
    assert " ".join(text[p.start : p.end] for p in pieces) == text


def test_split_oversized_prefers_clause_breaks():
    text = "alpha beta gamma delta, epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi"
    pieces = split_oversized(text, Span(0, len(text)), 40)
    assert text[pieces[0].start : pieces[0].end].endswith(",")


def test_split_oversized_cuts_hard_through_an_unbroken_run():
    text = "x" * 1000
    pieces = split_oversized(text, Span(0, len(text)), 300)
    assert all(piece.length <= 300 for piece in pieces)
    assert sum(piece.length for piece in pieces) == 1000
