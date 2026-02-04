from __future__ import annotations

import argparse
import asyncio
import os
import platform
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Lecture Upload</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
    :root {
      --bg: #f5f1e8;
      --ink: #1f1f1f;
      --muted: #5b5b5b;
      --accent: #1c6dd0;
      --accent-2: #ff8f4b;
      --card: #ffffff;
      --ok: #2e7d32;
      --warn: #b26a00;
      --err: #b00020;
    }
    * { box-sizing: border-box; }
    body {
      font-family: "Space Grotesk", system-ui, sans-serif;
      margin: 0;
      color: var(--ink);
      background: radial-gradient(circle at 10% 10%, #fff8e9, #f5f1e8 40%, #f1e7d6);
    }
    header {
      padding: 28px 40px 8px;
    }
    h1 { margin: 0; font-weight: 700; letter-spacing: -0.02em; }
    .sub { color: var(--muted); margin-top: 6px; }
    .wrap { padding: 20px 40px 60px; display: grid; gap: 18px; }
    .drop {
      border: 2px dashed #7a7a7a;
      border-radius: 18px;
      padding: 44px;
      text-align: center;
      color: #333;
      background: #fffdf7;
      transition: 160ms ease;
    }
    .drop.drag { background: #eef6ff; border-color: var(--accent); transform: translateY(-2px); }
    .grid { display: grid; gap: 12px; }
    .card {
      background: var(--card);
      border-radius: 16px;
      padding: 14px 16px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.06);
      border: 1px solid #f0e7d8;
    }
    .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .mono { font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 12px; color: #333; }
    .status { font-weight: 600; }
    .status.ok { color: var(--ok); }
    .status.warn { color: var(--warn); }
    .status.err { color: var(--err); }
    .progress {
      height: 10px;
      background: #eee3d2;
      border-radius: 999px;
      overflow: hidden;
      margin: 8px 0 4px;
    }
    .bar {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      transition: width 250ms ease;
    }
    .steps { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .step {
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      background: #f1eee7;
      color: #6b6b6b;
    }
    .step.active { background: #e7f1ff; color: var(--accent); }
    .step.done { background: #e6f4ea; color: var(--ok); }
    .step.error { background: #fde7e9; color: var(--err); }
    .meta { display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); font-size: 12px; margin-top: 6px; }
    .log { margin-top: 8px; color: var(--muted); font-size: 13px; }
  </style>
</head>
<body>
  <header>
    <h1>Lecture Upload</h1>
    <div class="sub">Drag a PDF to process locally and stream from your server.</div>
  </header>
  <div class="wrap">
    <div id="drop" class="drop">Drop PDF files here</div>
    <div id="cards" class="grid"></div>
  </div>
  <script>
    const drop = document.getElementById('drop');
    const cards = document.getElementById('cards');
    const steps = ['queued','analyzing','scripting','chunking','uploading','done'];

    const makeCard = (file) => {
      const el = document.createElement('div');
      el.className = 'card';
      el.innerHTML = `
        <div class="row">
          <div>
            <div><strong>${file.name}</strong></div>
            <div class="mono">size ${Math.round(file.size/1024)} KB</div>
          </div>
          <div class="status warn">queued</div>
        </div>
        <div class="progress"><div class="bar"></div></div>
        <div class="steps">
          ${steps.map(s => `<span class="step" data-step="${s}">${s}</span>`).join('')}
        </div>
        <div class="meta"></div>
        <div class="log"></div>
      `;
      cards.prepend(el);
      return el;
    };

    const updateCard = (el, status) => {
      const statusEl = el.querySelector('.status');
      statusEl.textContent = status.status;
      statusEl.className = 'status';
      if (status.status === 'done') statusEl.classList.add('ok');
      else if (status.status === 'error') statusEl.classList.add('err');
      else statusEl.classList.add('warn');
      el.querySelector('.bar').style.width = `${status.progress || 0}%`;
      const log = el.querySelector('.log');
      if (status.message) log.textContent = status.message;
      const meta = el.querySelector('.meta');
      const elapsed = status.elapsed_sec != null ? `${Math.round(status.elapsed_sec)}s elapsed` : '';
      const eta = status.eta_sec != null ? `${Math.round(status.eta_sec)}s remaining` : '';
      meta.textContent = [elapsed, eta].filter(Boolean).join(' • ');
      el.querySelectorAll('.step').forEach(stepEl => {
        const step = stepEl.dataset.step;
        stepEl.classList.remove('active','done','error');
        if (status.status === 'error' && step === status.status) {
          stepEl.classList.add('error');
        } else if (step === status.status) {
          stepEl.classList.add('active');
        } else if (steps.indexOf(step) < steps.indexOf(status.status)) {
          stepEl.classList.add('done');
        }
      });
    };

    const pollStatus = async (el, jobId) => {
      while (true) {
        const resp = await fetch(`/status/${jobId}`);
        const data = await resp.json();
        updateCard(el, data);
        if (data.status === 'done' || data.status === 'error') {
          break;
        }
        await new Promise(r => setTimeout(r, 1200));
      }
    };

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
          const el = makeCard(file);
          updateCard(el, { status: 'error', progress: 0, message: 'Only PDF files are supported.' });
          continue;
        }
        const el = makeCard(file);
        el.addEventListener('click', async () => {
          const jobId = el.dataset.jobId;
          if (!jobId) return;
          await fetch(`/reveal/${jobId}`, { method: 'POST' });
        });
        const form = new FormData();
        form.append('file', file);
        const resp = await fetch('/process', { method: 'POST', body: form });
        const data = await resp.json();
        if (!resp.ok) {
          updateCard(el, { status: 'error', progress: 0, message: data.detail || JSON.stringify(data) });
        } else {
          el.dataset.jobId = data.job_id;
          updateCard(el, { status: 'queued', progress: 5, message: 'Queued locally.' });
          pollStatus(el, data.job_id);
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


def _process_pdf_local(client: OpenAI, pdf_path: Path, lecture_id: str, title_hint: str) -> dict:
    chunks = analyze_pdf_chunks(client, pdf_path)
    script = merge_chunks_to_script(client, [c.data for c in chunks], title_hint)
    lecture_chunks = generate_lecture_chunks(script)

    script_path = settings.scripts_dir / f"{lecture_id}_lecture_script.json"
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    chunks_path = settings.chunks_dir / f"{lecture_id}.json"
    write_chunks(chunks_path, lecture_chunks)

    return {
        "lecture_id": lecture_id,
        "title": script.title,
        "source_filename": pdf_path.name,
        "lecture_script": script.model_dump(),
        "chunks": [chunk.model_dump() for chunk in lecture_chunks],
    }


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

    job_id = uuid.uuid4().hex
    upload_path = Path(settings.uploads_dir) / f"{job_id}_{filename}"
    contents = await file.read()
    upload_path.write_bytes(contents)

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "queued",
            "progress": 5,
            "message": "Queued locally.",
            "started_at": time.time(),
            "reveal_path": str(upload_path),
        }

    async def run_pipeline():
        try:
            with JOBS_LOCK:
                JOBS[job_id].update({"status": "analyzing", "progress": 20, "message": "Analyzing PDF pages."})
            client = OpenAI(api_key=settings.openai_api_key)
            payload = await asyncio.to_thread(
                _process_pdf_local, client, upload_path, job_id, upload_path.stem
            )
            with JOBS_LOCK:
                JOBS[job_id].update({"status": "scripting", "progress": 55, "message": "Drafting lecture script."})
            await asyncio.sleep(0)
            with JOBS_LOCK:
                JOBS[job_id].update({"status": "chunking", "progress": 70, "message": "Chunking lecture script."})
            await asyncio.sleep(0)
            with JOBS_LOCK:
                JOBS[job_id].update({"status": "uploading", "progress": 85, "message": "Uploading to server."})

            resp = await asyncio.to_thread(
                httpx.post,
                f"{SERVER_URL}/lectures/preprocessed",
                json=payload,
                headers=UPLOAD_HEADERS,
                timeout=60,
            )
            if resp.status_code >= 400:
                raise RuntimeError(resp.text)

            with JOBS_LOCK:
                JOBS[job_id].update(
                    {
                        "status": "done",
                        "progress": 100,
                        "message": f"Uploaded lecture {payload['lecture_id']}.",
                        "lecture_id": payload["lecture_id"],
                        "reveal_path": str(settings.scripts_dir / f"{job_id}_lecture_script.json"),
                    }
                )
        except Exception as exc:
            with JOBS_LOCK:
                JOBS[job_id].update({"status": "error", "progress": 0, "message": str(exc)})

    asyncio.create_task(run_pipeline())
    return JSONResponse({"job_id": job_id})


@APP.get("/status/{job_id}")
def status(job_id: str) -> JSONResponse:
    with JOBS_LOCK:
        payload = JOBS.get(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    started_at = payload.get("started_at")
    progress = payload.get("progress") or 0
    elapsed = time.time() - started_at if started_at else None
    eta = None
    if elapsed is not None and progress > 0:
        remaining_pct = max(0.0, 100.0 - float(progress))
        eta = elapsed * (remaining_pct / float(progress)) if progress > 0 else None
    return JSONResponse({**payload, "elapsed_sec": elapsed, "eta_sec": eta})


@APP.post("/reveal/{job_id}")
def reveal(job_id: str) -> JSONResponse:
    with JOBS_LOCK:
        payload = JOBS.get(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    path = payload.get("reveal_path")
    if not path:
        raise HTTPException(status_code=404, detail="No path to reveal")
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Path does not exist")

    system = platform.system().lower()
    if "darwin" in system:
        subprocess.run(["open", "-R", str(file_path)], check=False)
    elif "windows" in system:
        subprocess.run(["explorer", "/select,", str(file_path)], check=False)
    else:
        subprocess.run(["xdg-open", str(file_path.parent)], check=False)
    return JSONResponse({"status": "ok"})


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
