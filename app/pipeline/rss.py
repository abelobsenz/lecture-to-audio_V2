from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable, List

from jinja2 import Template

from app.config import settings
from app.db import Job, JobStatus


RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>Lecture to Audio</title>
  <link>{{ base_url }}</link>
  <description>Generated lectures from uploaded documents.</description>
  <language>en-us</language>
  <itunes:explicit>no</itunes:explicit>
  {% for item in items %}
  <item>
    <title>{{ item.title }}</title>
    <guid>{{ item.guid }}</guid>
    <pubDate>{{ item.pub_date }}</pubDate>
    <enclosure url="{{ item.url }}" length="{{ item.length }}" type="audio/{{ item.format }}" />
  </item>
  {% endfor %}
</channel>
</rss>
"""


def _rfc2822(dt_obj: dt.datetime) -> str:
    return dt_obj.strftime("%a, %d %b %Y %H:%M:%S GMT")


def generate_feed(jobs: Iterable[Job], output_path: Path) -> str:
    items: List[dict] = []
    for job in jobs:
        if job.status != JobStatus.done or not job.audio_path:
            continue
        audio_path = Path(job.audio_path)
        title = job.source_filename or job.id
        url = f"{settings.public_base_url}/jobs/{job.id}/audio"
        items.append(
            {
                "title": title,
                "guid": job.id,
                "pub_date": _rfc2822(job.updated_at),
                "url": url,
                "length": audio_path.stat().st_size if audio_path.exists() else 0,
                "format": audio_path.suffix.lstrip(".") or "m4a",
            }
        )

    xml = Template(RSS_TEMPLATE).render(base_url=settings.public_base_url, items=items)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml, encoding="utf-8")
    return xml
