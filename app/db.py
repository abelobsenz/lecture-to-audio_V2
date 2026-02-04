from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session


class JobStatus(str, Enum):
    queued = "queued"
    extracting = "extracting"
    scripting = "scripting"
    tts = "tts"
    syncing = "syncing"
    done = "done"
    failed = "failed"


class LectureStatus(str, Enum):
    queued = "queued"
    extracting = "extracting"
    scripting = "scripting"
    done = "done"
    failed = "failed"


class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    status: JobStatus = Field(default=JobStatus.queued)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.utcnow())
    updated_at: dt.datetime = Field(default_factory=lambda: dt.datetime.utcnow())
    source_filename: Optional[str] = Field(default=None)
    source_path: Optional[str] = Field(default=None)
    user_error: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
    traceback: Optional[str] = Field(default=None)
    script_path: Optional[str] = Field(default=None)
    audio_path: Optional[str] = Field(default=None)
    duration_sec: Optional[int] = Field(default=None)


class Lecture(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: Optional[str] = Field(default=None)
    source_filename: Optional[str] = Field(default=None)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.utcnow())
    updated_at: dt.datetime = Field(default_factory=lambda: dt.datetime.utcnow())
    status: LectureStatus = Field(default=LectureStatus.queued)
    lecture_script_json_path: Optional[str] = Field(default=None)
    chunks_json_path: Optional[str] = Field(default=None)
    cover_image_path: Optional[str] = Field(default=None)
    duration_sec: Optional[int] = Field(default=None)


class FileRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    kind: str
    path: str
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.utcnow())


class OutputRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    kind: str
    path: str
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.utcnow())


VALID_TRANSITIONS = {
    JobStatus.queued: {JobStatus.extracting, JobStatus.failed},
    JobStatus.extracting: {JobStatus.scripting, JobStatus.failed},
    JobStatus.scripting: {JobStatus.tts, JobStatus.done, JobStatus.failed},
    JobStatus.tts: {JobStatus.syncing, JobStatus.failed},
    JobStatus.syncing: {JobStatus.done, JobStatus.failed},
    JobStatus.done: set(),
    JobStatus.failed: set(),
}


def is_valid_transition(current: JobStatus, new: JobStatus) -> bool:
    return new in VALID_TRANSITIONS.get(current, set())


def apply_transition(job: Job, new_status: JobStatus) -> None:
    if not is_valid_transition(job.status, new_status):
        raise ValueError(f"Invalid transition: {job.status} -> {new_status}")
    job.status = new_status
    job.updated_at = dt.datetime.utcnow()


def get_engine(db_path: str = "sqlite:///data/lecture_to_audio.db"):
    return create_engine(db_path, connect_args={"check_same_thread": False})


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session(engine):
    return Session(engine)
