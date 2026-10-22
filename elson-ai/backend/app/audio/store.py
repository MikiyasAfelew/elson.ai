"""Where generated audio is kept (ADR-006, NFR-05).

Audio is content-addressed and per user: the storage key is built by `audio_storage_key`, and the
user id in its path is what keeps one user's audio away from another's. On top of that, each
document keeps a small *manifest* of the audio it used, so deleting a document can really delete
its audio (the privacy promise) without touching audio another document of the same user shares.

`LocalAudioStore` keeps files on disk and is meant for development and a single-VM launch. The
`AudioStore` protocol is what the rest of the code depends on, so an S3-compatible store (R2 or
MinIO) can replace it later without changes elsewhere. The manifest bookkeeping here is guarded by
a thread lock, which is enough for one process; a multi-process deployment needs the S3 version
to keep manifests in the database instead.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Protocol

from app.tts.base import AudioResult

# One path segment: starts with a letter or digit, so "." and ".." can never get through.
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class AudioStore(Protocol):
    def get(self, storage_key: str) -> AudioResult | None: ...

    def put(self, storage_key: str, audio: AudioResult) -> None: ...

    def link(self, user_id: str, document_id: str, storage_key: str) -> None:
        """Record that a document uses this audio."""
        ...

    def purge_document(self, user_id: str, document_id: str) -> int:
        """Delete the audio only this document uses. Returns how many files were removed."""
        ...

    def delete_user(self, user_id: str) -> None:
        """Delete everything stored for a user (account deletion)."""
        ...


def _segment(value: str) -> str:
    if not _SEGMENT.match(value):
        raise ValueError(f"unsafe path segment: {value!r}")
    return value


class LocalAudioStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._lock = threading.RLock()

    # ---- audio files -----------------------------------------------------------------------

    def _blob(self, storage_key: str) -> Path:
        return self._root.joinpath(*(_segment(part) for part in storage_key.split("/")))

    @staticmethod
    def _files(blob: Path) -> tuple[Path, Path]:
        return blob.with_name(blob.name + ".json"), blob.with_name(blob.name + ".bin")

    def get(self, storage_key: str) -> AudioResult | None:
        meta_path, data_path = self._files(self._blob(storage_key))
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            return AudioResult(
                data_path.read_bytes(),
                meta["codec"],
                int(meta["sample_rate"]),
                int(meta["duration_ms"]),
            )
        except (FileNotFoundError, KeyError, ValueError):
            return None  # missing or damaged: treated as a miss, so the audio is regenerated

    def put(self, storage_key: str, audio: AudioResult) -> None:
        meta_path, data_path = self._files(self._blob(storage_key))
        meta = {
            "codec": audio.codec,
            "sample_rate": audio.sample_rate,
            "duration_ms": audio.duration_ms,
        }
        # The metadata file is written last: its presence means the audio file is complete.
        _atomic_write(data_path, audio.data)
        _atomic_write(meta_path, json.dumps(meta).encode("utf-8"))

    # ---- manifests: which audio does each document use -------------------------------------

    def _manifest(self, user_id: str, document_id: str) -> Path:
        return self._root / "manifests" / _segment(user_id) / f"{_segment(document_id)}.json"

    @staticmethod
    def _read_manifest(path: Path) -> set[str]:
        try:
            return {str(key) for key in json.loads(path.read_text("utf-8"))}
        except (FileNotFoundError, ValueError, TypeError):
            return set()

    def link(self, user_id: str, document_id: str, storage_key: str) -> None:
        path = self._manifest(user_id, document_id)
        with self._lock:
            keys = self._read_manifest(path)
            if storage_key not in keys:
                keys.add(storage_key)
                _atomic_write(path, json.dumps(sorted(keys)).encode("utf-8"))

    def purge_document(self, user_id: str, document_id: str) -> int:
        path = self._manifest(user_id, document_id)
        with self._lock:
            mine = self._read_manifest(path)
            shared: set[str] = set()
            for other in path.parent.glob("*.json"):
                if other != path:
                    shared |= self._read_manifest(other)
            removed = 0
            for storage_key in mine - shared:
                for file in self._files(self._blob(storage_key)):
                    with contextlib.suppress(FileNotFoundError):
                        file.unlink()
                        removed += 1
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            return removed

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            for area in ("audio", "manifests"):
                shutil.rmtree(self._root / area / _segment(user_id), ignore_errors=True)


def _atomic_write(path: Path, data: bytes) -> None:
    """Write to a temporary file and rename it, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise
