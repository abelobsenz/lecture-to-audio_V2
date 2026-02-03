# lecture-to-audio

Upload PDFs and generate clean lecture-style audio using OpenAI, plus a realtime streaming lecture mode. The API runs on FastAPI and a background worker. A CLI is included for batch processing.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

Create `.env` from the example:

```bash
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`.

## Run the server

```bash
uvicorn app.main:app --reload
```

Endpoints (core):
- `POST /upload`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/script`
- `GET /jobs/{job_id}/audio`
- `GET /feed.xml`
- `GET /health`

Endpoints (lecture library + realtime):
- `GET /lectures`
- `GET /lectures/{lecture_id}`
- `GET /lectures/{lecture_id}/chunk?index=N`
- `GET /lectures/{lecture_id}/context?index=N&window=30`
- `GET /lectures/{lecture_id}/script`
- `GET /lectures/{lecture_id}/realtime-instructions`
- `POST /lectures/{lecture_id}/realtime-token`

## Two-model architecture

- Offline PDF analysis + script writing: `OPENAI_MODEL_ANALYSIS` (default `gpt-5.2`, fallback `gpt-5-mini`).
- Realtime streaming voice: `OPENAI_REALTIME_MODEL` (default `gpt-realtime`) with `OPENAI_REALTIME_VOICE`.

The analysis model is not a realtime audio model. The iOS client connects directly to OpenAI Realtime using an ephemeral token from this server.

## iOS streaming flow

1) Client requests `POST /lectures/{lecture_id}/realtime-token` to mint an ephemeral token.  
2) Client establishes WebRTC to OpenAI Realtime using the token.  
3) Client fetches `GET /lectures/{lecture_id}/chunk?index=N` and sends chunk text into the Realtime session.  
4) On STOP, client fetches `GET /lectures/{lecture_id}/context?index=N&window=30` and sends the question plus context.  
5) On OK, resume from the next chunk index.

## CLI batch mode

Process a folder of PDFs without running the server:

```bash
lecture-to-audio /path/to/pdfs
```

## iPhone sync (iCloud Drive)

Set `IOS_SYNC_DIR` to an iCloud Drive folder. Example macOS paths:

- `~/Library/Mobile Documents/com~apple~CloudDocs/LectureAudio`
- `~/Library/Mobile Documents/com~apple~CloudDocs/Podcasts/LectureAudio`

Final output name format:
`Title - YYYYMMDD - jobid.m4a`

## Podcast RSS on iPhone

Set `PUBLIC_BASE_URL` in `.env` (for example your local tunnel or server URL), then subscribe in a podcast app to:

`PUBLIC_BASE_URL/feed.xml`

## Troubleshooting

- Large PDFs: reduce `MAX_PAGES_PER_CHUNK` or use smaller input PDFs.
- Long TTS: audio is generated in segments and concatenated with `ffmpeg` if available. If `ffmpeg` is missing and output format is `m4a`, the server will return an `.m3u` playlist.
- OpenAI errors: verify `OPENAI_API_KEY` and model names in `.env`.

## Tests

```bash
pip install -e .[dev]
pytest
```

## Development notes

- Data directories are under `data/` for uploads, extracted chunks, scripts, audio, RSS, and lecture chunks.
- This MVP supports PDF processing; image and docx inputs are validated but not yet processed.
