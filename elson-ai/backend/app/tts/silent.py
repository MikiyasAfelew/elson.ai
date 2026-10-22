"""A stand-in engine that returns silence of the right length.

It lets the streaming, caching and playback code be built and tested end to end before a real
engine (MeloTTS, chosen in the Sprint 0 bake-off) is plugged in.
"""

from __future__ import annotations

import io
import wave

from app.tts.base import AudioResult, estimate_duration_ms

SAMPLE_RATE = 24_000


class SilentEngine:
    name = "silent"
    model_version = "1"
    codec = "wav"
    sample_rate = SAMPLE_RATE

    def synthesize(self, text: str, voice: str, lang: str, speed: float = 1.0) -> AudioResult:
        duration_ms = estimate_duration_ms(text, speed)
        frames = SAMPLE_RATE * duration_ms // 1000
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(b"\x00\x00" * frames)
        return AudioResult(buffer.getvalue(), "wav", SAMPLE_RATE, duration_ms)
