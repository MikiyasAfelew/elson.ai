import pytest

from app.cache.keys import audio_cache_key, audio_storage_key, pronunciations_used

BASE = {
    "text": "Nguyen walked home.",
    "voice": "narrator",
    "lang": "en",
    "engine": "melo",
    "model_version": "1.0",
    "sample_rate": 24000,
    "codec": "aac",
    "normalization_version": "1",
}


def key(**overrides) -> str:
    return audio_cache_key(**{**BASE, **overrides})


def test_the_same_inputs_give_the_same_key():
    assert key() == key()
    assert len(key()) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"text": "Nguyen walked away."},
        {"voice": "other"},
        {"lang": "fr"},
        {"engine": "kokoro"},
        {"model_version": "1.1"},
        {"sample_rate": 22050},
        {"codec": "wav"},
        {"normalization_version": "2"},
    ],
)
def test_changing_any_field_changes_the_key(change):
    assert key(**change) != key()


def test_fields_cannot_be_confused_by_shifting_characters_between_them():
    assert key(voice="ab", lang="c") != key(voice="a", lang="bc")


def test_only_pronunciation_entries_that_appear_in_the_chunk_matter():
    base = key(pronunciations={"Nguyen": "win"})
    assert key(pronunciations={"Nguyen": "win", "Siobhan": "shi-VAWN"}) == base
    assert key(pronunciations={"Nguyen": "nuh-win"}) != base
    assert base != key()


def test_pronunciation_matching_is_whole_word_and_case_insensitive():
    assert pronunciations_used("NGUYEN went", {"nguyen": "win"}) == [("nguyen", "win")]
    assert pronunciations_used("Nguyenville", {"Nguyen": "win"}) == []
    assert pronunciations_used("anything", None) == []
    assert pronunciations_used("anything", {"": "x"}) == []


def test_pronunciation_terms_with_regex_characters_are_matched_literally():
    assert pronunciations_used("the C++ book", {"C++": "see plus plus"}) == [
        ("C++", "see plus plus")
    ]


def test_storage_keys_are_per_user():
    digest = key()
    assert audio_storage_key("alice", digest) != audio_storage_key("bob", digest)
    assert audio_storage_key("alice", digest).startswith("audio/alice/")
