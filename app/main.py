from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import select

from app.config import settings
from app.db import Job, JobStatus, Lecture, LectureStatus, get_engine, get_session, init_db, FileRecord, OutputRecord
from app.chunking import build_context_text, get_chunk_by_index, load_chunks, write_chunks
from app.lectures import create_lecture_from_job, ensure_lecture
from app.pipeline.ingest import create_job_for_upload
from app.pipeline.worker import Worker
from app.pipeline.rss import generate_feed
from app.rate_limit import SimpleRateLimiter
from app.realtime import mint_realtime_client_secret
from app.schemas import (
    HealthResponse,
    JobResponse,
    UploadResponse,
    LectureSummary,
    LectureDetail,
    LectureChunkResponse,
    LectureContextResponse,
    RealtimeTokenResponse,
    RealtimeInstructionResponse,
    PreprocessedLectureUpload,
    PreprocessedUploadResponse,
    LectureStatusResponse,
)

app = FastAPI(title="lecture-to-audio")
engine = get_engine()
worker = Worker()
logging.basicConfig(level=logging.INFO)
rate_limiter = SimpleRateLimiter(settings.realtime_rate_limit_per_min, 60)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _lecture_ready(lecture: Lecture) -> bool:
    if lecture.status != LectureStatus.done:
        return False
    if not lecture.chunks_json_path:
        return False
    return Path(lecture.chunks_json_path).exists()


def _get_or_create_lecture(session, lecture_id: str) -> Lecture | None:
    lecture = session.get(Lecture, lecture_id)
    if lecture:
        return lecture
    job = session.get(Job, lecture_id)
    if not job:
        return None
    return ensure_lecture(session, job)


def _load_script_outline(script_path: Path) -> list[str]:
    try:
        data = script_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        from app.schemas import LectureScript

        script = LectureScript.model_validate_json(data)
    except Exception:
        return []
    return [chapter.name for chapter in script.chapters if chapter.name]


def build_realtime_instructions(title: str | None, outline: list[str]) -> str:
    parts = [
        "You are a lecturer delivering a clear, engaging lecture.",
        "Speak naturally and at a steady pace, using vivid language and concrete examples.",
        "You will receive lecture chunks from the client; read them aloud verbatim as narration.",
        "If the user interrupts with STOP and a question, answer using the provided recent context and lecture outline.",
        "If the user says 'forge ahead', continue from the next chunk.",
    ]
    if title:
        parts.insert(0, f"Lecture title: {title}.")
    if outline:
        parts.append(f"Lecture outline: {', '.join(outline)}.")
    return " ".join(parts)


def _verify_upload_token(token: str | None) -> None:
    if settings.upload_token and token != settings.upload_token:
        raise HTTPException(status_code=401, detail="Invalid upload token")


@app.on_event("startup")
async def startup() -> None:
    init_db(engine)
    for path in [
        settings.data_dir,
        settings.uploads_dir,
        settings.extracted_dir,
        settings.scripts_dir,
        settings.audio_dir,
        settings.rss_dir,
        settings.chunks_dir,
    ]:
        Path(path).mkdir(parents=True, exist_ok=True)
    worker.start()
    # Re-enqueue queued jobs
    with get_session(engine) as session:
        queued = session.exec(select(Job).where(Job.status == JobStatus.queued)).all()
        for job in queued:
            await worker.enqueue(job.id)


@app.on_event("shutdown")
async def shutdown() -> None:
    await worker.stop()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    file.file.seek(0, os.SEEK_END)
    size_bytes = file.file.tell()
    file.file.seek(0)

    try:
        job, saved_path = create_job_for_upload(file.filename, file.file, size_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    job_id = job.id
    with get_session(engine) as session:
        lecture = create_lecture_from_job(job)
        session.add(job)
        session.add(lecture)
        session.add(FileRecord(job_id=job.id, kind="upload", path=str(saved_path)))
        session.commit()

    await worker.enqueue(job_id)
    return UploadResponse(job_id=job_id)


@app.post("/lectures/preprocessed", response_model=PreprocessedUploadResponse)
def upload_preprocessed(
    payload: PreprocessedLectureUpload,
    upload_token: str | None = Header(default=None, alias="X-Upload-Token"),
) -> PreprocessedUploadResponse:
    _verify_upload_token(upload_token)
    lecture_id = payload.lecture_id or uuid.uuid4().hex
    with get_session(engine) as session:
        if session.get(Lecture, lecture_id) or session.get(Job, lecture_id):
            raise HTTPException(status_code=409, detail="Lecture already exists")

        now = dt.datetime.utcnow()
        script_path = settings.scripts_dir / f"{lecture_id}_lecture_script.json"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(payload.lecture_script.model_dump_json(indent=2), encoding="utf-8")

        chunks_path = settings.chunks_dir / f"{lecture_id}.json"
        write_chunks(chunks_path, payload.chunks)

        job = Job(
            id=lecture_id,
            status=JobStatus.done,
            created_at=now,
            updated_at=now,
            source_filename=payload.source_filename,
            script_path=str(script_path),
            audio_path=None,
            duration_sec=payload.lecture_script.duration_estimate_sec,
        )
        lecture = Lecture(
            id=lecture_id,
            title=payload.title or payload.lecture_script.title,
            source_filename=payload.source_filename,
            created_at=now,
            updated_at=now,
            status=LectureStatus.done,
            lecture_script_json_path=str(script_path),
            chunks_json_path=str(chunks_path),
            duration_sec=payload.lecture_script.duration_estimate_sec,
        )
        session.add(job)
        session.add(lecture)
        session.add(OutputRecord(job_id=lecture_id, kind="script", path=str(script_path)))
        session.add(OutputRecord(job_id=lecture_id, kind="chunks", path=str(chunks_path)))
        session.commit()

        if settings.enable_rss:
            jobs = session.exec(select(Job)).all()
            generate_feed(jobs, settings.rss_dir / "feed.xml")

    return PreprocessedUploadResponse(lecture_id=lecture_id, status=LectureStatus.done)


@app.get("/lectures/{lecture_id}/status", response_model=LectureStatusResponse)
def lecture_status(lecture_id: str) -> LectureStatusResponse:
    with get_session(engine) as session:
        lecture = _get_or_create_lecture(session, lecture_id)
        if not lecture:
            raise HTTPException(status_code=404, detail="Lecture not found")
        chunks_ready = bool(lecture.chunks_json_path and Path(lecture.chunks_json_path).exists())
        script_ready = bool(
            lecture.lecture_script_json_path and Path(lecture.lecture_script_json_path).exists()
        )
        return LectureStatusResponse(
            lecture_id=lecture.id,
            title=lecture.title,
            status=lecture.status,
            script_ready=script_ready,
            chunks_ready=chunks_ready,
        )


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    with get_session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobResponse(
            job_id=job.id,
            status=job.status,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
            source_filename=job.source_filename,
            audio_ready=bool(job.audio_path),
            script_ready=bool(job.script_path),
            user_error=job.user_error,
        )


@app.get("/jobs/{job_id}/script")
def get_script(job_id: str):
    with get_session(engine) as session:
        job = session.get(Job, job_id)
        if not job or not job.script_path:
            raise HTTPException(status_code=404, detail="Script not ready")
        return FileResponse(job.script_path, media_type="application/json")


@app.get("/jobs/{job_id}/audio")
def get_audio(job_id: str):
    with get_session(engine) as session:
        job = session.get(Job, job_id)
        if not job or not job.audio_path:
            raise HTTPException(status_code=404, detail="Audio not ready")
        path = Path(job.audio_path)
        media_type = "audio/*"
        if path.suffix == ".m3u":
            media_type = "audio/x-mpegurl"
        return FileResponse(str(path), media_type=media_type, filename=path.name)


@app.get("/lectures", response_model=list[LectureSummary])
def list_lectures(
    include_missing: bool = Query(default=False),
    include_non_done: bool = Query(default=False),
):
    with get_session(engine) as session:
        lectures = session.exec(select(Lecture)).all()
        jobs = session.exec(select(Job)).all()
        existing_ids = {lecture.id for lecture in lectures}
        for job in jobs:
            if job.id not in existing_ids:
                lectures.append(ensure_lecture(session, job))
        if not include_missing:
            filtered: list[Lecture] = []
            for lecture in lectures:
                if lecture.status != LectureStatus.done:
                    if include_non_done:
                        filtered.append(lecture)
                    continue
                chunks_path = lecture.chunks_json_path
                script_path = lecture.lecture_script_json_path
                if chunks_path and Path(chunks_path).exists() and script_path and Path(script_path).exists():
                    filtered.append(lecture)
            lectures = filtered
        lectures.sort(key=lambda item: item.created_at, reverse=True)
        items: list[LectureSummary] = []
        for lecture in lectures:
            title = lecture.title or (Path(lecture.source_filename).stem if lecture.source_filename else lecture.id)
            items.append(
                LectureSummary(
                    lecture_id=lecture.id,
                    title=title,
                    created_at=lecture.created_at.isoformat(),
                    status=lecture.status,
                    duration_estimate=lecture.duration_sec,
                )
            )
        return items


@app.get("/lectures/{lecture_id}", response_model=LectureDetail)
def get_lecture(lecture_id: str):
    with get_session(engine) as session:
        lecture = _get_or_create_lecture(session, lecture_id)
        if not lecture:
            raise HTTPException(status_code=404, detail="Lecture not found")
        chunks_ready = bool(lecture.chunks_json_path and Path(lecture.chunks_json_path).exists())
        script_ready = bool(
            lecture.lecture_script_json_path and Path(lecture.lecture_script_json_path).exists()
        )
        num_chunks = 0
        if chunks_ready:
            try:
                num_chunks = len(load_chunks(Path(lecture.chunks_json_path)))
            except Exception:
                num_chunks = 0
        title = lecture.title or (Path(lecture.source_filename).stem if lecture.source_filename else lecture.id)
        return LectureDetail(
            lecture_id=lecture.id,
            title=title,
            created_at=lecture.created_at.isoformat(),
            status=lecture.status,
            source_filename=lecture.source_filename,
            duration_estimate=lecture.duration_sec,
            num_chunks=num_chunks,
            chunks_ready=chunks_ready,
            script_ready=script_ready,
        )


@app.get("/lectures/{lecture_id}/chunk", response_model=LectureChunkResponse)
def get_lecture_chunk(lecture_id: str, index: int = Query(..., ge=0)):
    with get_session(engine) as session:
        lecture = _get_or_create_lecture(session, lecture_id)
        if not lecture:
            raise HTTPException(status_code=404, detail="Lecture not found")
        if not _lecture_ready(lecture):
            raise HTTPException(status_code=400, detail="Lecture not ready to stream")
        chunks = load_chunks(Path(lecture.chunks_json_path))
        try:
            chunk = get_chunk_by_index(chunks, index)
        except IndexError:
            raise HTTPException(status_code=404, detail="Chunk index out of range")
        return LectureChunkResponse(lecture_id=lecture_id, chunk=chunk)


@app.get("/lectures/{lecture_id}/context", response_model=LectureContextResponse)
def get_lecture_context(
    lecture_id: str, index: int = Query(..., ge=0), window: int = Query(30, ge=1)
):
    with get_session(engine) as session:
        lecture = _get_or_create_lecture(session, lecture_id)
        if not lecture:
            raise HTTPException(status_code=404, detail="Lecture not found")
        if not _lecture_ready(lecture):
            raise HTTPException(status_code=400, detail="Lecture not ready to stream")
        chunks = load_chunks(Path(lecture.chunks_json_path))
        if index >= len(chunks):
            raise HTTPException(status_code=404, detail="Chunk index out of range")
        context_text, approx_seconds = build_context_text(chunks, index, window)
        return LectureContextResponse(
            lecture_id=lecture_id,
            index=index,
            window=window,
            approx_seconds=approx_seconds,
            context_text=context_text,
        )


@app.get("/lectures/{lecture_id}/script")
def get_lecture_script(lecture_id: str):
    with get_session(engine) as session:
        lecture = _get_or_create_lecture(session, lecture_id)
        if not lecture:
            raise HTTPException(status_code=404, detail="Lecture not found")
        script_path = lecture.lecture_script_json_path
        if not script_path:
            job = session.get(Job, lecture_id)
            if job and job.script_path:
                script_path = job.script_path
        if not script_path or not Path(script_path).exists():
            raise HTTPException(status_code=404, detail="Script not ready")
        return FileResponse(script_path, media_type="application/json")


@app.get(
    "/lectures/{lecture_id}/realtime-instructions",
    response_model=RealtimeInstructionResponse,
)
def get_realtime_instructions(lecture_id: str):
    with get_session(engine) as session:
        lecture = _get_or_create_lecture(session, lecture_id)
        if not lecture:
            raise HTTPException(status_code=404, detail="Lecture not found")
        outline: list[str] = []
        if lecture.lecture_script_json_path:
            outline = _load_script_outline(Path(lecture.lecture_script_json_path))
        title = lecture.title or (Path(lecture.source_filename).stem if lecture.source_filename else lecture.id)
        instructions = build_realtime_instructions(title, outline)
        return RealtimeInstructionResponse(lecture_id=lecture_id, instructions=instructions)


@app.post(
    "/lectures/{lecture_id}/realtime-token",
    response_model=RealtimeTokenResponse,
)
def create_realtime_token(lecture_id: str, request: Request):
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    with get_session(engine) as session:
        lecture = _get_or_create_lecture(session, lecture_id)
        if not lecture:
            raise HTTPException(status_code=404, detail="Lecture not found")
        if not _lecture_ready(lecture):
            raise HTTPException(status_code=400, detail="Lecture not ready to stream")

    client_secret = mint_realtime_client_secret(
        settings.openai_api_key,
        settings.openai_realtime_model,
        settings.openai_realtime_voice,
    )
    return RealtimeTokenResponse(
        client_secret=client_secret,
        realtime_model=settings.openai_realtime_model,
        voice=settings.openai_realtime_voice,
        lecture_id=lecture_id,
        server_time=dt.datetime.utcnow().isoformat(),
    )


@app.get("/feed.xml")
def feed():
    if not settings.enable_rss:
        raise HTTPException(status_code=404, detail="RSS feed disabled")
    with get_session(engine) as session:
        jobs = session.exec(select(Job)).all()
        xml = generate_feed(jobs, settings.rss_dir / "feed.xml")
    return PlainTextResponse(content=xml, media_type="application/rss+xml")
