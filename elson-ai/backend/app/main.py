"""HTTP API (FastAPI). Thin: every route calls DocumentService and converts the result.

Until accounts arrive (Sprint 6) every request acts as one local user.
"""

from __future__ import annotations

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.audio.http import RangeNotSatisfiable, parse_byte_range
from app.audio.service import AudioService
from app.audio.store import LocalAudioStore
from app.config import Settings
from app.errors import AppError
from app.schemas import (
    BookmarkIn,
    BookmarkOut,
    ChunkOut,
    ChunkPage,
    DocumentOut,
    ProgressIn,
    ProgressOut,
)
from app.service import DocumentService
from app.store import InMemoryRepository
from app.tts.silent import SilentEngine

LOCAL_USER = "local"
API_PREFIX = "/api/v1"
MEDIA_TYPES = {"wav": "audio/wav", "aac": "audio/aac", "mp3": "audio/mpeg", "flac": "audio/flac"}


def create_app(
    settings: Settings | None = None,
    repository: InMemoryRepository | None = None,
    audio_service: AudioService | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    service = DocumentService(repository or InMemoryRepository(), settings)
    # Until a real voice is chosen in the Sprint 0 bake-off, the silent engine stands in.
    audio = audio_service or AudioService(LocalAudioStore(settings.audio_dir), SilentEngine())

    app = FastAPI(title="Elson.ai API", version="0.1.0")
    app.state.service = service
    app.state.audio = audio
    app.state.settings = settings

    def svc(request: Request) -> DocumentService:
        return request.app.state.service

    # ---- errors: every failure is a short code plus a message fit to be spoken aloud --------

    @app.exception_handler(AppError)
    async def app_error(_: Request, error: AppError) -> JSONResponse:
        return JSONResponse(error.to_dict(), status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "code": "INVALID_REQUEST",
                "message": "That request wasn't quite right. Check what you sent and try again.",
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, error: StarletteHTTPException) -> JSONResponse:
        if error.status_code == 404:
            body = {"code": "NOT_FOUND", "message": "We couldn't find that."}
        else:
            body = {"code": "REQUEST_FAILED", "message": "Something went wrong with that request."}
        return JSONResponse(body, status_code=error.status_code)

    # ---- routes ------------------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(f"{API_PREFIX}/documents", status_code=201, response_model=DocumentOut)
    async def upload_document(request: Request, file: UploadFile = File(...)) -> DocumentOut:
        # Read one byte past the limit so an oversized file is detected without loading it all.
        data = await file.read(settings.max_upload_bytes + 1)
        document = await run_in_threadpool(
            svc(request).create_document, LOCAL_USER, file.filename, data
        )
        return DocumentOut.of(document)

    @app.get(f"{API_PREFIX}/documents", response_model=list[DocumentOut])
    async def list_documents(request: Request) -> list[DocumentOut]:
        return [DocumentOut.of(d) for d in svc(request).list_documents(LOCAL_USER)]

    @app.get(f"{API_PREFIX}/documents/{{document_id}}", response_model=DocumentOut)
    async def get_document(request: Request, document_id: str) -> DocumentOut:
        return DocumentOut.of(svc(request).get_document(LOCAL_USER, document_id))

    @app.delete(f"{API_PREFIX}/documents/{{document_id}}", status_code=204)
    async def delete_document(request: Request, document_id: str) -> Response:
        svc(request).delete_document(LOCAL_USER, document_id)
        # The privacy promise: deleting a document deletes the audio made from it.
        await run_in_threadpool(request.app.state.audio.purge_document, LOCAL_USER, document_id)
        return Response(status_code=204)

    @app.get(f"{API_PREFIX}/documents/{{document_id}}/chunks", response_model=ChunkPage)
    async def get_chunks(
        request: Request,
        document_id: str,
        start: int = Query(0),
        limit: int = Query(20),
    ) -> ChunkPage:
        service = svc(request)
        chunks, next_start = service.get_chunks(LOCAL_USER, document_id, start, limit)
        total = len(service.get_document(LOCAL_USER, document_id).chunks)
        return ChunkPage(items=[ChunkOut.of(c) for c in chunks], next_start=next_start, total=total)

    @app.get(f"{API_PREFIX}/documents/{{document_id}}/chunks/{{index}}/audio")
    async def get_chunk_audio(request: Request, document_id: str, index: int) -> Response:
        document = svc(request).get_document(LOCAL_USER, document_id)
        # Synthesis blocks, so it runs in a worker thread, off the event loop.
        result = await run_in_threadpool(
            request.app.state.audio.get_audio, LOCAL_USER, document, index
        )
        etag = f'"{result.cache_key}"'
        headers = {"ETag": etag, "Cache-Control": "private, no-cache", "Accept-Ranges": "bytes"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        data = result.audio.data
        try:
            byte_range = parse_byte_range(request.headers.get("range"), len(data))
        except RangeNotSatisfiable:
            headers["Content-Range"] = f"bytes */{len(data)}"
            return Response(status_code=416, headers=headers)
        media_type = MEDIA_TYPES.get(result.audio.codec, "application/octet-stream")
        if byte_range is None:
            return Response(data, media_type=media_type, headers=headers)
        start, end = byte_range
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
        return Response(
            data[start : end + 1], status_code=206, headers=headers, media_type=media_type
        )

    @app.put(f"{API_PREFIX}/documents/{{document_id}}/progress", response_model=ProgressOut)
    async def put_progress(request: Request, document_id: str, body: ProgressIn) -> ProgressOut:
        service = svc(request)
        progress = service.save_progress(LOCAL_USER, document_id, body.char_offset, body.device_id)
        document = service.get_document(LOCAL_USER, document_id)
        return ProgressOut.of(progress, service.locate(document, progress.char_offset))

    @app.get(f"{API_PREFIX}/documents/{{document_id}}/progress", response_model=ProgressOut)
    async def get_progress(request: Request, document_id: str) -> ProgressOut:
        result = svc(request).get_progress(LOCAL_USER, document_id)
        if result is None:
            raise AppError("NO_PROGRESS", "You haven't started this document yet.", 404)
        return ProgressOut.of(*result)

    @app.post(
        f"{API_PREFIX}/documents/{{document_id}}/bookmarks",
        status_code=201,
        response_model=BookmarkOut,
    )
    async def post_bookmark(request: Request, document_id: str, body: BookmarkIn) -> BookmarkOut:
        bookmark = svc(request).add_bookmark(LOCAL_USER, document_id, body.char_offset, body.label)
        return BookmarkOut.of(bookmark)

    @app.get(f"{API_PREFIX}/documents/{{document_id}}/bookmarks", response_model=list[BookmarkOut])
    async def get_bookmarks(request: Request, document_id: str) -> list[BookmarkOut]:
        return [BookmarkOut.of(b) for b in svc(request).list_bookmarks(LOCAL_USER, document_id)]

    return app


app = create_app()
