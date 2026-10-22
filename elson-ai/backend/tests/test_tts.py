import io
import wave

import pytest

from app.tts.base import estimate_duration_ms
from app.tts.silent import SAMPLE_RATE, SilentEngine


def test_estimated_duration_scales_with_length_and_speed():
    assert estimate_duration_ms("x" * 150) == 10_000
    assert estimate_duration_ms("x" * 150, speed=2.0) == 5_000
    assert estimate_duration_ms("") == 300  # never zero


def test_a_non_positive_speed_is_rejected():
    with pytest.raises(ValueError):
        estimate_duration_ms("hello", speed=0)


def test_silent_engine_returns_a_valid_wav_of_the_estimated_length():
    result = SilentEngine().synthesize("x" * 150, voice="narrator", lang="en")
    assert (result.codec, result.sample_rate, result.duration_ms) == ("wav", SAMPLE_RATE, 10_000)
    with wave.open(io.BytesIO(result.data)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == SAMPLE_RATE
        assert wav.getnframes() == SAMPLE_RATE * 10
