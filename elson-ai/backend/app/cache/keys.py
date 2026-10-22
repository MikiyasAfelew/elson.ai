"""Cache keys for generated audio (ADR-006).

A key changes exactly when the audio would change: the text, the voice, the engine and model
version, the audio format, the normalization version, and only those pronunciation entries whose
term actually appears in the chunk. Editing one dictionary word therefore re-renders only the
chunks that contain it.

Audio is cached per user (never shared between users) except for public-domain catalog titles.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping


def pronunciations_used(
    text: str, pronunciations: Mapping[str, str] | None
) -> list[tuple[str, str]]:
    """The (term, respelling) pairs whose term appears in `text` as a whole word, sorted."""
    if not pronunciations:
        return []
    used = [
        (term, respelling)
        for term, respelling in pronunciations.items()
        if term and re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)
    ]
    return sorted(used)


def audio_cache_key(
    *,
    text: str,
    voice: str,
    lang: str,
    engine: str,
    model_version: str,
    sample_rate: int,
    codec: str,
    normalization_version: str,
    pronunciations: Mapping[str, str] | None = None,
) -> str:
    entries = json.dumps(pronunciations_used(text, pronunciations), ensure_ascii=False)
    fields = [
        text,
        voice,
        lang,
        engine,
        model_version,
        str(sample_rate),
        codec,
        normalization_version,
        entries,
    ]
    digest = hashlib.sha256()
    for field in fields:
        encoded = field.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))  # length prefix: no ambiguous joins
        digest.update(encoded)
    return digest.hexdigest()


def audio_storage_key(user_id: str, cache_key: str) -> str:
    """Object-storage path. The user id prefix is what keeps audio per user."""
    return f"audio/{user_id}/{cache_key[:2]}/{cache_key}"
