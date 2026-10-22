# Elson.ai

Accessibility-first document-to-audio for blind and visually impaired listeners. Design and
decisions live in the *Elson.ai: Architecture & Technical Documentation* doc (v0.2); this README
covers only how to run and work on the code.

## Run

```bash
cd backend
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://localhost:8000/docs
pytest -q && ruff check . && ruff format --check .
```

Or `docker compose up --build` from the repository root.

## Try it

```bash
curl -F file=@story.txt http://localhost:8000/api/v1/documents          # returns a document id
curl http://localhost:8000/api/v1/documents/<id>/chunks
curl -o chunk0.wav http://localhost:8000/api/v1/documents/<id>/chunks/0/audio
```

Audio is currently silence of the right length: the real voice is chosen in the Sprint 0
bake-off, and the engine plugs in behind `app/tts/base.py` without other changes.

## Layout (`backend/app`)

| Module | Job |
|---|---|
| `ingestion/` | Read an uploaded file into text (TXT now; EPUB and PDF in Sprints 4-5) |
| `normalize/` | Clean text, detect chapters, cut sentence-aware chunks (all offsets point into one canonical text) |
| `tts/` | Engine contract (`TTSEngine`) and the silent stand-in engine |
| `audio/` | Per-user audio store, rolling-window planner, get-or-create service, HTTP range parsing |
| `cache/` | Audio cache keys: change exactly when the audio would |
| `service.py`, `store.py` | Documents, progress, bookmarks (in memory until Sprint 6) |
| `main.py` | Thin HTTP layer; every error is a code plus a message fit to be spoken aloud |

## Status

| Sprint | State |
|---|---|
| 0 Spikes | Not started: gapless playback, voice bake-off, respelling vs IPA, cost, Flutter accessibility |
| 1 Upload, cleaner, chunker, API | Done |
| 2 Audio store, rolling window, range delivery | Done in code; **SSE events, a background worker and a real voice are still to do** |
| 3+ Flutter player, EPUB/PDF, accounts, pronunciation, beta | Not started |

Known limits: single local user, in-memory documents, one process. Nothing here has been run
against a real browser, device or screen reader yet.
