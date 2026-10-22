"""The TTS engine contract. Engines are swappable behind this interface (section 5.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# A rough speaking rate for estimates only (characters per second at 1.0x).
CHARS_PER_SECOND = 15.0


@dataclass(frozen=True)
class AudioResult:
    data: bytes
    codec: str  # "wav", "aac", ...
    sample_rate: int
    duration_ms: int


class TTSEngine(Protocol):
    name: str
    model_version: str
    codec: str  # what `synthesize` returns; part of the audio cache key
    sample_rate: int

    def synthesize(self, text: str, voice: str, lang: str, speed: float = 1.0) -> AudioResult:
        """Render `text` to audio. Speed is a hint; the client time-stretches playback itself."""
        ...


def estimate_duration_ms(text: str, speed: float = 1.0) -> int:
    """Estimated spoken length of `text`, for scheduling before real audio exists."""
    if speed <= 0:
        raise ValueError("speed must be positive")
    return max(300, round(len(text) / CHARS_PER_SECOND / speed * 1000))
