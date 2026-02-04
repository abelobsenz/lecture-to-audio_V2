from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from openai import OpenAI
from pypdf import PdfReader

from app.config import settings


@dataclass
class ChunkResult:
    start_page: int
    end_page: int
    data: Dict[str, Any]


def _page_count(pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


_INVALID_ESCAPE_RE = re.compile(r'\\(?!["\\/bfnrtu])')


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text


def _extract_json_block(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _coerce_json(text: str) -> Dict[str, Any]:
    return json.loads(text)


def _safe_json_loads(text: str) -> Dict[str, Any]:
    cleaned = _extract_json_block(_strip_code_fences(text))
    try:
        return _coerce_json(cleaned)
    except json.JSONDecodeError:
        repaired = _INVALID_ESCAPE_RE.sub(r"\\\\", cleaned)
        return _coerce_json(repaired)


def _repair_json_with_model(client: OpenAI, text: str) -> str:
    prompt = (
        "Fix the following JSON. Return ONLY valid JSON with the same keys/structure. "
        "Do not add commentary or code fences.\n\n"
        f"{text}"
    )
    model_name = settings.openai_model_fallback or settings.openai_model_analysis
    response = client.responses.create(
        model=model_name,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                ],
            }
        ],
    )
    repaired_text = getattr(response, "output_text", None)
    if not repaired_text and getattr(response, "output", None):
        parts = []
        for out in response.output:
            for content in getattr(out, "content", []):
                if getattr(content, "type", "") in {"output_text", "text"}:
                    parts.append(getattr(content, "text", ""))
        repaired_text = "\n".join(parts)
    if not repaired_text:
        raise RuntimeError("No text output returned from model")
    return _strip_code_fences(repaired_text)


def upload_pdf(client: OpenAI, pdf_path: Path) -> str:
    with pdf_path.open("rb") as f:
        file_obj = client.files.create(file=f, purpose="assistants")
    return file_obj.id


def analyze_pdf_chunks(client: OpenAI, pdf_path: Path) -> List[ChunkResult]:
    file_id = upload_pdf(client, pdf_path)
    total_pages = _page_count(pdf_path)
    results: List[ChunkResult] = []

    page = 1
    while page <= total_pages:
        start_page = page
        end_page = min(page + settings.max_pages_per_chunk - 1, total_pages)
        prompt = (
            "You are analyzing a PDF lecture or paper. "
            f"Focus ONLY on pages {start_page} to {end_page}. "
            "Extract structured understanding. Output JSON only with keys: "
            "chunk_summary, key_definitions, theorems, equations, figures, tables. "
            "equations should be a list of {latex, meaning, intuition}. "
            "figures should be a list of {id, type, description, axes, trend, significance}. "
            "tables should be a list of {id, description, key_rows, key_columns}."
        )

        model_name = settings.openai_model_fallback or settings.openai_model_analysis
        response = client.responses.create(
            model=model_name,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_file", "file_id": file_id},
                    ],
                }
            ],
        )
        text = getattr(response, "output_text", None)
        if not text and getattr(response, "output", None):
            # Best-effort extraction for SDK variants
            parts = []
            for out in response.output:
                for content in getattr(out, "content", []):
                    if getattr(content, "type", "") in {"output_text", "text"}:
                        parts.append(getattr(content, "text", ""))
            text = "\n".join(parts)
        if not text:
            raise RuntimeError("No text output returned from model")
        try:
            data = _safe_json_loads(text)
        except json.JSONDecodeError:
            repaired_text = _repair_json_with_model(client, text)
            data = _safe_json_loads(repaired_text)
        results.append(ChunkResult(start_page=start_page, end_page=end_page, data=data))
        page = end_page + 1
    return results
