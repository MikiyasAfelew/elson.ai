"""HTTP tests. They need FastAPI and its test client; they are skipped where those are missing
(CI installs them from requirements-dev.txt)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

BODY = "The rain kept falling over the quiet town. " * 15
STORY = f"Chapter 1\n\nThe Storm\n\n{BODY}\n\n{BODY}\n\nChapter 2\n\n{BODY}\n\n{BODY}"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(max_upload_bytes=50_000, audio_dir=str(tmp_path / "audio"))
    return TestClient(create_app(settings))


STORY_BYTES = STORY.encode()


def upload(client, name="story.txt", data=STORY_BYTES):
    return client.post("/api/v1/documents", files={"file": (name, data, "text/plain")})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_returns_the_processed_document(client):
    response = upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "story"
    assert body["status"] == "ready"
    assert [c["title"] for c in body["chapters"]] == ["Chapter 1: The Storm", "Chapter 2"]
    assert body["chunk_count"] > 0
    assert client.get(f"/api/v1/documents/{body['id']}").json() == body
    assert [d["id"] for d in client.get("/api/v1/documents").json()] == [body["id"]]


def test_chunks_are_paged(client):
    document = upload(client).json()
    first = client.get(
        f"/api/v1/documents/{document['id']}/chunks", params={"start": 0, "limit": 2}
    )
    page = first.json()
    assert [c["index"] for c in page["items"]] == [0, 1]
    assert page["next_start"] == 2
    assert page["total"] == document["chunk_count"]


def test_unsupported_and_coming_soon_files_get_spoken_errors(client):
    pdf = upload(client, "book.pdf", b"%PDF-1.4 ...")
    assert pdf.status_code == 415
    assert pdf.json()["code"] == "NOT_YET_SUPPORTED"
    image = upload(client, "photo.png", b"\x89PNG\r\n")
    assert image.status_code == 415
    assert image.json()["code"] == "UNSUPPORTED_FILE"


def test_oversized_uploads_are_refused(client):
    response = upload(client, data=b"x" * 50_001)
    assert response.status_code == 413
    assert response.json()["code"] == "FILE_TOO_LARGE"


def test_missing_documents_and_routes_have_the_standard_error_shape(client):
    missing = client.get("/api/v1/documents/doc_nope")
    assert missing.status_code == 404
    assert missing.json()["code"] == "DOCUMENT_NOT_FOUND"
    unknown = client.get("/api/v1/nothing-here")
    assert unknown.status_code == 404
    assert set(unknown.json()) == {"code", "message"}


def test_invalid_requests_have_the_standard_error_shape(client):
    document = upload(client).json()
    response = client.put(f"/api/v1/documents/{document['id']}/progress", json={"char_offset": -1})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"
    no_file = client.post("/api/v1/documents")
    assert no_file.status_code == 422
    assert set(no_file.json()) == {"code", "message"}


def test_progress_and_bookmarks(client):
    document = upload(client).json()
    base = f"/api/v1/documents/{document['id']}"
    assert client.get(f"{base}/progress").json()["code"] == "NO_PROGRESS"

    saved = client.put(f"{base}/progress", json={"char_offset": 700, "device_id": "phone"})
    assert saved.status_code == 200
    assert saved.json()["char_offset"] == 700
    assert saved.json()["chunk_index"] is not None
    client.put(f"{base}/progress", json={"char_offset": 50, "device_id": "laptop"})

    created = client.post(f"{base}/bookmarks", json={"char_offset": 300, "label": "Good part"})
    assert created.status_code == 201
    labels = [b["label"] for b in client.get(f"{base}/bookmarks").json()]
    assert labels == ["Good part", "Previous position"]


def test_delete(client):
    document = upload(client).json()
    url = f"/api/v1/documents/{document['id']}"
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def audio_url(document_id: str, index: int = 0) -> str:
    return f"/api/v1/documents/{document_id}/chunks/{index}/audio"


def test_chunk_audio_is_served_as_wav_with_an_etag(client):
    document = upload(client).json()
    response = client.get(audio_url(document["id"]))
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content[:4] == b"RIFF"
    assert response.headers["etag"].startswith('"')


def test_an_unchanged_chunk_answers_not_modified(client):
    document = upload(client).json()
    etag = client.get(audio_url(document["id"])).headers["etag"]
    again = client.get(audio_url(document["id"]), headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""


def test_chunk_audio_supports_byte_ranges(client):
    document = upload(client).json()
    whole = client.get(audio_url(document["id"])).content

    part = client.get(audio_url(document["id"]), headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.content == whole[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(whole)}"

    beyond = client.get(audio_url(document["id"]), headers={"Range": f"bytes={len(whole)}-"})
    assert beyond.status_code == 416
    assert beyond.headers["content-range"] == f"bytes */{len(whole)}"


def test_a_chunk_that_does_not_exist_gets_a_spoken_error(client):
    document = upload(client).json()
    missing = client.get(audio_url(document["id"], document["chunk_count"]))
    assert missing.status_code == 404
    assert missing.json()["code"] == "CHUNK_NOT_FOUND"
    assert client.get(audio_url("doc_nope")).json()["code"] == "DOCUMENT_NOT_FOUND"


def test_deleting_a_document_deletes_its_audio_files(client, tmp_path):
    document = upload(client).json()
    client.get(audio_url(document["id"]))
    audio_root = tmp_path / "audio" / "audio"
    assert any(audio_root.rglob("*.bin"))

    assert client.delete(f"/api/v1/documents/{document['id']}").status_code == 204
    assert not any(audio_root.rglob("*.bin"))
