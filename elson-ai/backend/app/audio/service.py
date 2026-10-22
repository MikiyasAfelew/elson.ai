"""Get-or-create audio for a chunk, and fill the rolling window ahead of the playhead.

Synthesis is CPU-heavy and blocking, so callers run it off the event loop (a threadpool now, a
Celery `tts` worker later). A per-key lock means two requests for the same chunk, for example the
player and the prefetcher, synthesize it once, not twice.
"""

from __future__ import annotations

import contextlib
import re
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from app.audio.store import AudioStore
from app.audio.window import DEFAULT_WINDOW_MS, plan_window
from app.cache.keys import audio_cache_key, audio_storage_key, pronunciations_used
from app.config import PIPELINE_VERSION
from app.errors import AppError
from app.models import Document
from app.normalize.chunker import Chunk
from app.tts.base import AudioResult, TTSEngine

DEFAULT_VOICE = "narrator"
DEFAULT_LANG = "en"


@dataclass(frozen=True)
class ChunkAudio:
    audio: AudioResult
    cache_key: str
    cache_hit: bool


@dataclass(frozen=True)
class PrefetchReport:
    generated: tuple[int, ...]  # chunk indexes synthesized by this call
    cached: tuple[int, ...]  # chunk indexes that already had audio


class AudioService:
    def __init__(self, store: AudioStore, engine: TTSEngine) -> None:
        self._store = store
        self._engine = engine
        self._guard = threading.Lock()
        self._locks: dict[str, list] = {}  # storage key -> [lock, number of users]

    # ---- one chunk -------------------------------------------------------------------------

    def get_audio(
        self,
        user_id: str,
        document: Document,
        chunk_index: int,
        *,
        voice: str = DEFAULT_VOICE,
        lang: str | None = None,
        pronunciations: Mapping[str, str] | None = None,
    ) -> ChunkAudio:
        chunk = self._chunk(document, chunk_index)
        lang = lang or document.language or DEFAULT_LANG
        cache_key = self._cache_key(chunk, voice, lang, pronunciations)
        storage_key = audio_storage_key(user_id, cache_key)

        audio = self._store.get(storage_key)
        hit = audio is not None
        if audio is None:
            with self._key_lock(storage_key):
                audio = self._store.get(storage_key)  # another request may have just made it
                hit = audio is not None
                if audio is None:
                    audio = self._engine.synthesize(
                        _speakable(chunk.text, pronunciations), voice, lang
                    )
                    self._store.put(storage_key, audio)
        self._store.link(user_id, document.id, storage_key)
        return ChunkAudio(audio, cache_key, hit)

    # ---- the rolling window ----------------------------------------------------------------

    def prefetch(
        self,
        user_id: str,
        document: Document,
        playhead_offset: int,
        *,
        window_ms: int = DEFAULT_WINDOW_MS,
        voice: str = DEFAULT_VOICE,
        lang: str | None = None,
        pronunciations: Mapping[str, str] | None = None,
        max_new: int | None = None,
    ) -> PrefetchReport:
        """Make sure the window ahead of `playhead_offset` has audio.

        `max_new` bounds how many chunks one call may synthesize, so a worker can do the work in
        small jobs and the urgent chunks (the first of the window) are always done first.
        """
        generated: list[int] = []
        cached: list[int] = []
        for item in plan_window(document.chunks, playhead_offset, window_ms=window_ms):
            lang_used = lang or document.language or DEFAULT_LANG
            storage_key = audio_storage_key(
                user_id,
                self._cache_key(document.chunks[item.index], voice, lang_used, pronunciations),
            )
            if self._store.get(storage_key) is not None:
                self._store.link(user_id, document.id, storage_key)
                cached.append(item.index)
                continue
            if max_new is not None and len(generated) >= max_new:
                break
            self.get_audio(
                user_id,
                document,
                item.index,
                voice=voice,
                lang=lang,
                pronunciations=pronunciations,
            )
            generated.append(item.index)
        return PrefetchReport(tuple(generated), tuple(cached))

    # ---- deletion --------------------------------------------------------------------------

    def purge_document(self, user_id: str, document_id: str) -> int:
        return self._store.purge_document(user_id, document_id)

    def delete_user(self, user_id: str) -> None:
        self._store.delete_user(user_id)

    # ---- internals -------------------------------------------------------------------------

    @staticmethod
    def _chunk(document: Document, chunk_index: int) -> Chunk:
        if not 0 <= chunk_index < len(document.chunks):
            raise AppError(
                "CHUNK_NOT_FOUND", "That part of the document doesn't exist.", status_code=404
            )
        return document.chunks[chunk_index]

    def _cache_key(
        self, chunk: Chunk, voice: str, lang: str, pronunciations: Mapping[str, str] | None
    ) -> str:
        return audio_cache_key(
            text=chunk.text,
            voice=voice,
            lang=lang,
            engine=self._engine.name,
            model_version=self._engine.model_version,
            sample_rate=self._engine.sample_rate,
            codec=self._engine.codec,
            normalization_version=PIPELINE_VERSION,
            pronunciations=pronunciations,
        )

    @contextlib.contextmanager
    def _key_lock(self, key: str) -> Iterator[None]:
        with self._guard:
            entry = self._locks.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._guard:
                entry[1] -= 1
                if entry[1] == 0:
                    del self._locks[key]  # nobody is waiting: forget the lock


def _speakable(text: str, pronunciations: Mapping[str, str] | None) -> str:
    """Replace each dictionary term found in `text` with its respelling, for the engine."""
    for term, respelling in pronunciations_used(text, pronunciations):
        text = re.sub(
            rf"(?<!\w){re.escape(term)}(?!\w)",
            lambda _match, spoken=respelling: spoken,
            text,
            flags=re.IGNORECASE,
        )
    return text
