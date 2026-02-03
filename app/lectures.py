from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

from sqlmodel import Session

from app.config import settings
from app.db import Job, Lecture, LectureStatus


def _title_from_filename(filename: Optional[str], fallback: str) -> str:
    if filename:
        return Path(filename).stem
    return fallback


def _map_job_status(job_status) -> LectureStatus:
    value = getattr(job_status, "value", job_status)
    if value in {"queued", "extracting", "scripting"}:
        return LectureStatus(value)
    if value == "failed":
        return LectureStatus.failed
    return LectureStatus.done


def create_lecture_from_job(job: Job) -> Lecture:
    title = _title_from_filename(job.source_filename, job.id)
    chunks_path = settings.chunks_dir / f"{job.id}.json"
    chunks_value = str(chunks_path) if chunks_path.exists() else None
    return Lecture(
        id=job.id,
        title=title,
        source_filename=job.source_filename,
        created_at=job.created_at,
        updated_at=job.updated_at,
        status=_map_job_status(job.status),
        lecture_script_json_path=job.script_path,
        chunks_json_path=chunks_value,
        cover_image_path=None,
        duration_sec=job.duration_sec,
    )


def ensure_lecture(session: Session, job: Job) -> Lecture:
    lecture = session.get(Lecture, job.id)
    if lecture:
        return lecture
    lecture = create_lecture_from_job(job)
    session.add(lecture)
    session.commit()
    session.refresh(lecture)
    return lecture


def update_lecture_status(lecture: Lecture, status: LectureStatus) -> None:
    lecture.status = status
    lecture.updated_at = dt.datetime.utcnow()
