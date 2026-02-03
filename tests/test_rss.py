import datetime as dt
from pathlib import Path

from app.config import settings
from app.db import Job, JobStatus
from app.pipeline.rss import generate_feed


def test_generate_feed(tmp_path: Path):
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"abc")
    job = Job(
        id="job123",
        status=JobStatus.done,
        source_filename="lecture.pdf",
        audio_path=str(audio),
        updated_at=dt.datetime(2025, 1, 1),
    )
    settings.public_base_url = "http://example.com"
    output_path = tmp_path / "feed.xml"
    xml = generate_feed([job], output_path)

    assert output_path.exists()
    assert "job123" in xml
    assert "http://example.com/jobs/job123/audio" in xml
