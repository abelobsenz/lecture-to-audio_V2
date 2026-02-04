from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import traceback
from pathlib import Path
from typing import Optional

from openai import OpenAI
from sqlmodel import select

from app.config import settings
from app.db import Job, JobStatus, Lecture, LectureStatus, OutputRecord, apply_transition, get_engine, get_session
from app.lectures import ensure_lecture
from app.pipeline.analyze_pdf import analyze_pdf_chunks
from app.chunking import generate_lecture_chunks, write_chunks
from app.pipeline.script_writer import merge_chunks_to_script, simple_fallback_script
from app.pipeline.tts import generate_audio
from app.pipeline.rss import generate_feed
from app.storage.local import LocalStorage


class Worker:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.engine = get_engine()
        self.storage = LocalStorage()
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.logger = logging.getLogger("lecture_to_audio.worker")

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                await asyncio.sleep(settings.worker_poll_interval_sec)
                continue
            try:
                await asyncio.to_thread(self.process_job, job_id)
            finally:
                self.queue.task_done()

    def _update_status(self, job: Job, lecture: Lecture | None, status: JobStatus) -> None:
        apply_transition(job, status)
        if lecture is not None:
            lecture.status = self._map_lecture_status(status)
            lecture.updated_at = dt.datetime.utcnow()

    @staticmethod
    def _map_lecture_status(job_status: JobStatus) -> LectureStatus:
        if job_status == JobStatus.queued:
            return LectureStatus.queued
        if job_status == JobStatus.extracting:
            return LectureStatus.extracting
        if job_status == JobStatus.scripting:
            return LectureStatus.scripting
        if job_status == JobStatus.failed:
            return LectureStatus.failed
        return LectureStatus.done

    def process_job(self, job_id: str) -> None:
        with get_session(self.engine) as session:
            job = session.get(Job, job_id)
            if not job:
                return
            lecture = ensure_lecture(session, job)
            try:
                self.logger.info("Starting job %s", job_id)
                if not settings.openai_api_key:
                    raise RuntimeError("OPENAI_API_KEY is not set")
                self._update_status(job, lecture, JobStatus.extracting)
                session.add(job)
                session.add(lecture)
                session.commit()
                self.logger.info("Job %s extracting", job_id)

                pdf_path = Path(job.source_path)
                if pdf_path.suffix.lower() != ".pdf":
                    raise ValueError("Only PDF processing is supported in this MVP")
                chunks = analyze_pdf_chunks(self.client, pdf_path)
                extracted_path = settings.extracted_dir / f"{job.id}_chunks.json"
                extracted_path.parent.mkdir(parents=True, exist_ok=True)
                extracted_path.write_text(
                    json.dumps([c.data for c in chunks], indent=2), encoding="utf-8"
                )
                session.add(
                    OutputRecord(job_id=job.id, kind="extracted", path=str(extracted_path))
                )

                self._update_status(job, lecture, JobStatus.scripting)
                session.add(job)
                session.add(lecture)
                session.commit()
                self.logger.info("Job %s scripting", job_id)

                try:
                    script = merge_chunks_to_script(
                        self.client, [c.data for c in chunks], job.source_filename or job.id
                    )
                except Exception:
                    script = simple_fallback_script(
                        [c.data for c in chunks], job.source_filename or job.id
                    )

                script_path = settings.scripts_dir / f"{job.id}_lecture_script.json"
                script_path.parent.mkdir(parents=True, exist_ok=True)
                script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
                session.add(
                    OutputRecord(job_id=job.id, kind="script", path=str(script_path))
                )

                lecture.title = script.title
                lecture.lecture_script_json_path = str(script_path)
                lecture.duration_sec = script.duration_estimate_sec

                chunks = generate_lecture_chunks(script)
                chunks_path = settings.chunks_dir / f"{job.id}.json"
                write_chunks(chunks_path, chunks)
                lecture.chunks_json_path = str(chunks_path)

                job.script_path = str(script_path)
                job.duration_sec = script.duration_estimate_sec
                session.add(job)
                session.add(lecture)
                session.commit()

                if not settings.enable_audio_generation:
                    self._update_status(job, lecture, JobStatus.done)
                    session.add(job)
                    session.add(lecture)
                    session.commit()
                    self.logger.info("Job %s done (audio disabled)", job_id)
                    if settings.enable_rss:
                        jobs = session.exec(select(Job)).all()
                        generate_feed(jobs, settings.rss_dir / "feed.xml")
                    return

                self._update_status(job, lecture, JobStatus.tts)
                session.add(job)
                session.add(lecture)
                session.commit()
                self.logger.info("Job %s tts", job_id)

                audio_suffix = "." + settings.openai_tts_format
                audio_path = settings.audio_dir / f"{job.id}{audio_suffix}"
                audio_out = generate_audio(self.client, script, audio_path)
                session.add(
                    OutputRecord(job_id=job.id, kind="audio", path=str(audio_out))
                )

                self._update_status(job, lecture, JobStatus.syncing)
                job.audio_path = str(audio_out)
                session.add(job)
                session.add(lecture)
                session.commit()
                self.logger.info("Job %s syncing", job_id)

                if settings.ios_sync_dir and Path(job.audio_path).exists():
                    cleaned_title = (job.source_filename or job.id).rsplit(".", 1)[0]
                    date_str = dt.datetime.utcnow().strftime("%Y%m%d")
                    dest_name = f"{cleaned_title} - {date_str} - {job.id}{Path(job.audio_path).suffix}"
                    dest_path = settings.ios_sync_dir / dest_name
                    self.storage.copy(Path(job.audio_path), dest_path)

                self._update_status(job, lecture, JobStatus.done)
                session.add(job)
                session.add(lecture)
                session.commit()
                self.logger.info("Job %s done", job_id)

                # Update RSS feed
                if settings.enable_rss:
                    jobs = session.exec(select(Job)).all()
                    generate_feed(jobs, settings.rss_dir / "feed.xml")

            except Exception as exc:
                self.logger.exception("Job %s failed", job_id)
                job = session.get(Job, job_id)
                if job:
                    try:
                        apply_transition(job, JobStatus.failed)
                    except Exception:
                        job.status = JobStatus.failed
                        job.updated_at = dt.datetime.utcnow()
                    if lecture:
                        lecture.status = LectureStatus.failed
                        lecture.updated_at = dt.datetime.utcnow()
                    job.user_error = "Processing failed. Please try again or check logs."
                    job.error = repr(exc)
                    job.traceback = traceback.format_exc()
                    session.add(job)
                    if lecture:
                        session.add(lecture)
                    session.commit()
