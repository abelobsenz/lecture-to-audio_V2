from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI

from app.chunking import generate_lecture_chunks, write_chunks
from app.config import settings
from app.pipeline.analyze_pdf import analyze_pdf_chunks
from app.pipeline.script_writer import merge_chunks_to_script


APP = FastAPI(title="Lecture Drop Upload")
SERVER_URL: str | None = None
UPLOAD_HEADERS: dict[str, str] = {}

HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Lecture Upload</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif; margin: 40px; }
    .drop {
      border: 2px dashed #888; border-radius: 16px; padding: 48px; text-align: center;
      color: #444; background: #fafafa;
    }
    .drop.drag { background: #eef6ff; border-color: #1c6dd0; }
    .log { margin-top: 20px; font-size: 14px; white-space: pre-wrap; }
  </style>
</head>
<body>
  <h2>Drag & Drop PDF</h2>
  <div id="drop" class="drop">Drop a PDF here</div>
  <div id="log" class="log"></div>
  <script>
    const drop = document.getElementById('drop');
    const log = document.getElementById('log');
    const addLog = (msg) => { log.textContent = msg + "\\n" + log.textContent; };

    ['dragenter','dragover'].forEach(evt => {
      drop.addEventListener(evt, e => {
        e.preventDefault(); e.stopPropagation(); drop.classList.add('drag');
      });
    });
    ['dragleave','drop'].forEach(evt => {
      drop.addEventListener(evt, e => {
        e.preventDefault(); e.stopPropagation(); drop.classList.remove('drag');
      });
    });
    drop.addEventListener('drop', async e => {
      const files = [...e.dataTransfer.files];
      if (!files.length) return;
      for (const file of files) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
          addLog(`Skipped non-PDF: ${file.name}`);
          continue;
        }
        addLog(`Processing ${file.name}...`);
        const form = new FormData();
        form.append('file', file);
        const resp = await fetch('/process', { method: 'POST', body: form });
        const data = await resp.json();
        if (!resp.ok) {
          addLog(`Error: ${data.detail || JSON.stringify(data)}`);
        } else {
          addLog(`Uploaded lecture ${data.lecture_id} (${file.name})`);
        }
      }
    });
  </script>
</body>
</html>
"""


def _ensure_dirs() -> None:
    for path in [settings.data_dir, settings.scripts_dir, settings.chunks_dir, settings.uploads_dir]:
        Path(path).mkdir(parents=True, exist_ok=True)


def _process_pdf_local(client: OpenAI, pdf_path: Path, title_hint: str) -> tuple[str, Path, Path]:
    lecture_id = uuid.uuid4().hex
    chunks = analyze_pdf_chunks(client, pdf_path)
    script = merge_chunks_to_script(client, [c.data for c in chunks], title_hint)
    lecture_chunks = generate_lecture_chunks(script)

    script_path = settings.scripts_dir / f"{lecture_id}_lecture_script.json"
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    chunks_path = settings.chunks_dir / f"{lecture_id}.json"
    write_chunks(chunks_path, lecture_chunks)

    payload = {
        "lecture_id": lecture_id,
        "title": script.title,
        "source_filename": pdf_path.name,
        "lecture_script": script.model_dump(),
        "chunks": [chunk.model_dump() for chunk in lecture_chunks],
    }

    return lecture_id, payload, script_path


@APP.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(HTML)


@APP.post("/process")
async def process(file: UploadFile = File(...)) -> JSONResponse:
    if SERVER_URL is None:
        raise HTTPException(status_code=500, detail="Server URL not configured")
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

    _ensure_dirs()
    filename = Path(file.filename or "upload.pdf").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    upload_path = Path(settings.uploads_dir) / filename
    contents = await file.read()
    upload_path.write_bytes(contents)

    client = OpenAI(api_key=settings.openai_api_key)
    lecture_id, payload, _ = await asyncio.to_thread(_process_pdf_local, client, upload_path, upload_path.stem)

    resp = await asyncio.to_thread(
        httpx.post,
        f"{SERVER_URL}/lectures/preprocessed",
        json=payload,
        headers=UPLOAD_HEADERS,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    return JSONResponse({"lecture_id": lecture_id, "status": "uploaded"})


def main() -> None:
    global SERVER_URL, UPLOAD_HEADERS
    parser = argparse.ArgumentParser(description="Local drag-and-drop PDF processor/uploader.")
    parser.add_argument("--server", required=True, help="Server base URL, e.g. https://example.com")
    parser.add_argument("--host", default="127.0.0.1", help="Local host to bind")
    parser.add_argument("--port", type=int, default=8085, help="Local port to bind")
    parser.add_argument("--token", default=os.environ.get("UPLOAD_TOKEN"), help="Upload token (optional)")
    args = parser.parse_args()

    SERVER_URL = args.server.rstrip("/")
    if args.token:
        UPLOAD_HEADERS = {"X-Upload-Token": args.token}

    import uvicorn

    uvicorn.run(APP, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
