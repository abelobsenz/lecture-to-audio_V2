from __future__ import annotations

import datetime as dt
import mimetypes
import uuid
from pathlib import Path
from typing import BinaryIO, Tuple

from app.config import settings
from app.db import FileRecord, Job, JobStatus
from app.storage.local import LocalStorage


ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx"}


def _safe_ext(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_upload(filename: str, size_bytes: int) -> None:
    ext = _safe_ext(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")
    if size_bytes > settings.max_upload_mb * 1024 * 1024:
        raise ValueError("File too large")


def create_job_for_upload(filename: str, file_obj: BinaryIO, size_bytes: int) -> Tuple[Job, Path]:
    safe_filename = Path(filename).name
    validate_upload(safe_filename, size_bytes)
    job_id = uuid.uuid4().hex
    ext = _safe_ext(safe_filename)
    safe_name = f"{job_id}{ext}"
    dest = settings.uploads_dir / safe_name

    storage = LocalStorage()
    storage.save_upload(file_obj, dest)

    job = Job(
        id=job_id,
        status=JobStatus.queued,
        created_at=dt.datetime.utcnow(),
        updated_at=dt.datetime.utcnow(),
        source_filename=safe_filename,
        source_path=str(dest),
    )
    return job, dest


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"
