from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlmodel import select

from app.config import settings
from app.db import FileRecord, Job, JobStatus, get_engine, get_session, init_db
from app.lectures import create_lecture_from_job
from app.pipeline.ingest import create_job_for_upload
from app.pipeline.worker import Worker


def _iter_pdfs(input_dir: Path):
    for path in input_dir.rglob("*.pdf"):
        if path.is_file():
            yield path


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch process PDFs into lecture audio")
    parser.add_argument("input_dir", type=str, help="Folder containing PDFs")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        raise SystemExit(f"Input dir does not exist: {input_dir}")

    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY not set")

    engine = get_engine()
    init_db(engine)

    worker = Worker()

    for pdf_path in _iter_pdfs(input_dir):
        with pdf_path.open("rb") as f:
            size_bytes = pdf_path.stat().st_size
            job, saved_path = create_job_for_upload(pdf_path.name, f, size_bytes)

        with get_session(engine) as session:
            lecture = create_lecture_from_job(job)
            session.add(job)
            session.add(lecture)
            session.add(FileRecord(job_id=job.id, kind="upload", path=str(saved_path)))
            session.commit()

        worker.process_job(job.id)
        print(f"Processed {pdf_path.name} -> job {job.id}")


if __name__ == "__main__":
    main()
