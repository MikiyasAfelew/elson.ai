"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Bump when the cleaner or chunker output changes. Progress and bookmarks store this value
# next to a character offset, so old positions can be remapped after a pipeline change.
PIPELINE_VERSION = "1"


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 50 * 1024 * 1024
    audio_dir: str = "./data/audio"  # generated audio and its manifests (local store)

    @classmethod
    def from_env(cls) -> Settings:
        megabytes = int(os.getenv("ELSON_MAX_UPLOAD_MB", "50"))
        return cls(
            max_upload_bytes=megabytes * 1024 * 1024,
            audio_dir=os.getenv("ELSON_AUDIO_DIR", "./data/audio"),
        )
