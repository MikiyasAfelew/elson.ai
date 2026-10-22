import threading
import time
from datetime import UTC, datetime

import pytest

from app.audio.service import AudioService
from app.audio.store import LocalAudioStore
from app.audio.window import plan_window
from app.errors import AppError
from app.models import Document
from app.pipeline import process_text
from app.tts.silent import SilentEngine

SENTENCE = "Dr. Okonkwo walked to the harbour and watched the boats drift out. "
TEXT = "\n\n".join(SENTENCE * 18 for _ in range(14))


class CountingEngine(SilentEngine):
    """Records every request, and can be slowed down to expose races."""

    name = "counting"

    def __init__(self, delay: float = 0.0) -> None:
        self.texts: list[str] = []
        self._delay = delay
        self._lock = threading.Lock()

    def synthesize(self, text, voice, lang, speed=1.0):
        with self._lock:
            self.texts.append(text)
        if self._delay:
            time.sleep(self._delay)
        return super().synthesize(text, voice, lang, speed)


def make_document(owner: str = "alice", doc_id: str = "doc_1") -> Document:
    processed = process_text(TEXT)
    return Document(
        id=doc_id,
        user_id=owner,
        title="Harbour",
        source_kind="txt",
        filename="harbour.txt",
        created_at=datetime.now(UTC),
        text=processed.text,
        chapters=processed.chapters,
        chunks=processed.chunks,
        pipeline_version=processed.pipeline_version,
    )


@pytest.fixture
def engine() -> CountingEngine:
    return CountingEngine()


@pytest.fixture
def service(tmp_path, engine) -> AudioService:
    return AudioService(LocalAudioStore(tmp_path), engine)


@pytest.fixture
def document() -> Document:
    document = make_document()
    assert len(document.chunks) > 8  # the tests below rely on a multi-chunk document
    return document


def test_the_first_request_synthesizes_and_the_second_is_served_from_the_cache(
    service, engine, document
):
    first = service.get_audio("alice", document, 0)
    second = service.get_audio("alice", document, 0)

    assert (first.cache_hit, second.cache_hit) == (False, True)
    assert first.cache_key == second.cache_key
    assert first.audio == second.audio
    assert len(engine.texts) == 1


def test_a_different_voice_is_a_different_cache_entry(service, engine, document):
    narrator = service.get_audio("alice", document, 0)
    other = service.get_audio("alice", document, 0, voice="storyteller")

    assert narrator.cache_key != other.cache_key
    assert len(engine.texts) == 2


def test_a_missing_chunk_is_reported_in_plain_words(service, document):
    for index in (-1, len(document.chunks)):
        with pytest.raises(AppError) as caught:
            service.get_audio("alice", document, index)
        assert caught.value.code == "CHUNK_NOT_FOUND"
        assert caught.value.status_code == 404


def test_two_users_never_share_audio(service, engine):
    service.get_audio("alice", make_document("alice"), 0)
    service.get_audio("bob", make_document("bob"), 0)
    assert len(engine.texts) == 2  # same text, but each user pays for and owns their copy


def test_a_respelling_reaches_the_engine_but_never_the_document(service, engine, document):
    respelling = {"Okonkwo": "oh-KONG-kwoh"}
    service.get_audio("alice", document, 0, pronunciations=respelling)

    assert "oh-KONG-kwoh" in engine.texts[0]
    assert "Okonkwo" not in engine.texts[0]
    assert "Okonkwo" in document.chunks[0].text


def test_editing_a_dictionary_word_only_renders_chunks_that_contain_it(service, engine, document):
    service.get_audio("alice", document, 0)
    service.get_audio("alice", document, 0, pronunciations={"Zanzibar": "zan-zi-bar"})
    assert len(engine.texts) == 1  # the term is not in chunk 0, so its audio is reused

    service.get_audio("alice", document, 0, pronunciations={"Okonkwo": "oh-KONG-kwoh"})
    assert len(engine.texts) == 2  # now the chunk does contain it


def test_simultaneous_requests_for_one_chunk_synthesize_it_once(tmp_path, document):
    engine = CountingEngine(delay=0.05)
    service = AudioService(LocalAudioStore(tmp_path), engine)
    gate = threading.Barrier(8)
    results = []

    def request():
        gate.wait()
        results.append(service.get_audio("alice", document, 0))

    threads = [threading.Thread(target=request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 8
    assert len(engine.texts) == 1
    assert sorted(r.cache_hit for r in results).count(False) == 1
    assert service._locks == {}  # no lock is left behind


def test_prefetch_fills_the_window_and_a_second_call_finds_it_ready(service, document):
    window_ms = 120_000
    expected = [i.index for i in plan_window(document.chunks, 0, window_ms=window_ms)]

    first = service.prefetch("alice", document, 0, window_ms=window_ms)
    second = service.prefetch("alice", document, 0, window_ms=window_ms)

    assert list(first.generated) == expected
    assert first.cached == ()
    assert second.generated == ()
    assert list(second.cached) == expected


def test_prefetch_can_be_limited_and_always_does_the_earliest_chunks_first(service, document):
    report = service.prefetch("alice", document, 0, window_ms=10**9, max_new=3)
    assert report.generated == (0, 1, 2)

    later = service.prefetch("alice", document, 0, window_ms=10**9, max_new=2)
    assert later.generated == (3, 4)
    assert later.cached == (0, 1, 2)


def test_prefetch_starts_at_the_playhead_not_at_the_beginning(service, document):
    target = document.chunks[5]
    report = service.prefetch("alice", document, target.char_start + 3, window_ms=1, max_new=1)
    assert report.generated == (5,)


def test_deleting_a_document_deletes_its_audio(service, engine, document):
    service.get_audio("alice", document, 0)
    assert service.purge_document("alice", document.id) > 0

    again = service.get_audio("alice", document, 0)
    assert again.cache_hit is False
    assert len(engine.texts) == 2
