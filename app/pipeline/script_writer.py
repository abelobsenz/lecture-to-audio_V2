from __future__ import annotations

import json
from typing import Any, Dict, List

from openai import OpenAI

from app.config import settings
from app.schemas import LectureScript


def _safe_json_loads(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def merge_chunks_to_script(client: OpenAI, chunks: List[Dict[str, Any]], title_hint: str) -> LectureScript:
    prompt = (
        "You are an expert lecturer. Given chunk analyses, produce a lecture script JSON. "
        "Follow this schema strictly: "
        "{title, source_type, duration_estimate_sec, chapters:[{name, narration, spoken_math:[{latex, spoken, intuition}], "
        "figure_narration:[{figure_id, description (detailed enough to construct a mental image), chart_type, axes, trend, significance}]}], final_recap}. "
        "Rules: narration must be natural spoken text, no raw LaTeX. "
        "For spoken_math, convert LaTeX into speech, defining terms if they have not yet been introduced. "
        "Figure narration must describe axes/units, trends, comparisons, and why it matters. "
        "Include smooth transitions between chapters. Pause for five seconds in between chapters."
    )

    response = client.responses.create(
        model=settings.openai_model_analysis,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_text", "text": f"Title hint: {title_hint}"},
                    {"type": "input_text", "text": json.dumps(chunks)},
                ],
            }
        ],
    )
    text = getattr(response, "output_text", None)
    if not text and getattr(response, "output", None):
        parts = []
        for out in response.output:
            for content in getattr(out, "content", []):
                if getattr(content, "type", "") in {"output_text", "text"}:
                    parts.append(getattr(content, "text", ""))
        text = "\n".join(parts)
    if not text:
        raise RuntimeError("No text output returned from model")
    data = _safe_json_loads(text)
    return LectureScript(**data)


def simple_fallback_script(chunks: List[Dict[str, Any]], title_hint: str) -> LectureScript:
    chapters = []
    for idx, ch in enumerate(chunks, start=1):
        summary = ch.get("chunk_summary") or "Summary missing."
        chapters.append(
            {
                "name": f"Section {idx}",
                "narration": summary,
                "spoken_math": [],
                "figure_narration": [],
            }
        )
    data = {
        "title": title_hint or "Lecture",
        "source_type": "pdf",
        "duration_estimate_sec": max(60, 60 * len(chapters)),
        "chapters": chapters,
        "final_recap": "We covered the main ideas from the document.",
    }
    return LectureScript(**data)
