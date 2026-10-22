import pytest

from app.audio.store import LocalAudioStore
from app.tts.base import AudioResult

KEY_A = "audio/alice/ab/abc123"
KEY_B = "audio/alice/cd/cde456"


def audio(payload: bytes = b"RIFFdata") -> AudioResult:
    return AudioResult(payload, "wav", 24_000, 1_500)


@pytest.fixture
def store(tmp_path) -> LocalAudioStore:
    return LocalAudioStore(tmp_path)


def test_audio_survives_a_round_trip(store):
    store.put(KEY_A, audio(b"hello"))
    assert store.get(KEY_A) == audio(b"hello")


def test_a_missing_key_is_a_miss(store):
    assert store.get(KEY_A) is None


def test_damaged_metadata_is_a_miss_not_a_crash(store, tmp_path):
    store.put(KEY_A, audio())
    (tmp_path / "audio" / "alice" / "ab" / "abc123.json").write_text("{not json")
    assert store.get(KEY_A) is None


def test_audio_without_its_metadata_is_a_miss(store, tmp_path):
    # A write that died between the two files must not look like finished audio.
    store.put(KEY_A, audio())
    (tmp_path / "audio" / "alice" / "ab" / "abc123.json").unlink()
    assert store.get(KEY_A) is None


def test_writes_leave_no_temporary_files(store, tmp_path):
    store.put(KEY_A, audio())
    store.link("alice", "doc_1", KEY_A)
    assert not [p for p in tmp_path.rglob("*") if p.name.startswith(".tmp-")]


def test_keys_that_could_escape_the_store_are_rejected(store):
    for bad in ("../secret", "audio/../../x", "audio//x", "/etc/passwd", "audio/.hidden/x", ""):
        with pytest.raises(ValueError):
            store.put(bad, audio())
    with pytest.raises(ValueError):
        store.link("../bob", "doc_1", KEY_A)


def test_purging_a_document_keeps_audio_another_document_still_uses(store):
    for key in (KEY_A, KEY_B):
        store.put(key, audio())
    store.link("alice", "doc_1", KEY_A)
    store.link("alice", "doc_1", KEY_B)
    store.link("alice", "doc_2", KEY_B)

    removed = store.purge_document("alice", "doc_1")

    assert removed == 2  # KEY_A's audio and metadata files
    assert store.get(KEY_A) is None
    assert store.get(KEY_B) is not None
    assert store.purge_document("alice", "doc_2") == 2  # now nothing else holds KEY_B
    assert store.get(KEY_B) is None


def test_purging_an_unknown_document_does_nothing(store):
    assert store.purge_document("alice", "doc_missing") == 0


def test_linking_twice_is_harmless(store):
    store.put(KEY_A, audio())
    store.link("alice", "doc_1", KEY_A)
    store.link("alice", "doc_1", KEY_A)
    assert store.purge_document("alice", "doc_1") == 2


def test_deleting_a_user_removes_only_that_users_data(store):
    store.put(KEY_A, audio())
    store.link("alice", "doc_1", KEY_A)
    bob_key = "audio/bob/ab/abc123"
    store.put(bob_key, audio())
    store.link("bob", "doc_9", bob_key)

    store.delete_user("alice")

    assert store.get(KEY_A) is None
    assert store.purge_document("alice", "doc_1") == 0
    assert store.get(bob_key) is not None
