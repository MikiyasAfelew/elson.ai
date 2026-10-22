import codecs

import pytest

from app.errors import AppError
from app.ingestion import extract_text
from app.ingestion.kinds import detect_kind, safe_filename, title_from_filename
from app.ingestion.txt import decode_text


def test_decodes_utf8():
    assert decode_text("café — naïve".encode()) == "café — naïve"


def test_decodes_legacy_windows_1252_text():
    assert decode_text(b"caf\xe9 \x93quoted\x94") == "café \u201cquoted\u201d"


def test_decodes_utf8_and_utf16_with_a_byte_order_mark():
    assert decode_text(codecs.BOM_UTF8 + "héllo".encode()) == "héllo"
    assert decode_text("héllo".encode("utf-16")) == "héllo"


def test_undefined_bytes_never_crash_decoding():
    assert "\ufffd" in decode_text(b"abc\x81def")


def test_binary_data_is_rejected_with_a_spoken_message():
    with pytest.raises(AppError) as error:
        decode_text(b"\x00\x01\x02binary\x00data")
    assert error.value.code == "UNSUPPORTED_FILE"
    assert error.value.status_code == 415


@pytest.mark.parametrize(
    ("filename", "head", "kind"),
    [
        ("story.txt", b"Once upon", "txt"),
        ("story.TXT", b"Once upon", "txt"),
        ("story", b"Once upon", "txt"),
        ("book.pdf", b"%PDF-1.7", "pdf"),
        ("renamed.txt", b"%PDF-1.7", "pdf"),
        ("book.epub", b"PK\x03\x04", "epub"),
        ("report.docx", b"PK\x03\x04", "docx"),
        ("archive.zip", b"PK\x03\x04", "unknown"),
        ("fake.pdf", b"Not really a pdf", "unknown"),
        ("image.png", b"\x89PNG", "unknown"),
    ],
)
def test_detects_file_kinds_from_name_and_content(filename, head, kind):
    assert detect_kind(filename, head) == kind


def test_filenames_cannot_carry_a_path():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\Users\\me\\story.txt") == "story.txt"
    assert safe_filename(None) == ""


def test_titles_come_from_the_filename():
    assert title_from_filename("my_great-story.txt") == "my great story"
    assert title_from_filename(None) == "Untitled"
    assert title_from_filename("") == "Untitled"


def test_extracts_text_from_a_txt_upload():
    extracted = extract_text("tale.txt", b"Once upon a time.")
    assert (extracted.kind, extracted.text, extracted.title) == ("txt", "Once upon a time.", "tale")


@pytest.mark.parametrize(
    ("filename", "head"),
    [("book.pdf", b"%PDF-1.4"), ("book.epub", b"PK\x03\x04"), ("memo.docx", b"PK\x03\x04")],
)
def test_formats_that_are_coming_soon_say_so_honestly(filename, head):
    with pytest.raises(AppError) as error:
        extract_text(filename, head + b"....")
    assert error.value.code == "NOT_YET_SUPPORTED"
    assert "coming soon" in error.value.message
    assert error.value.status_code == 415


def test_unknown_formats_are_rejected():
    with pytest.raises(AppError) as error:
        extract_text("photo.png", b"\x89PNG\r\n")
    assert error.value.code == "UNSUPPORTED_FILE"


def test_error_dict_has_only_a_code_and_a_message():
    error = AppError("SOME_CODE", "Something to say aloud.", 418)
    assert error.to_dict() == {"code": "SOME_CODE", "message": "Something to say aloud."}
