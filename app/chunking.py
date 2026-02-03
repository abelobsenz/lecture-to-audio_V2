from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List, Tuple

from app.config import settings
from app.schemas import Chapter, LectureChunk, LectureScript

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"\b\w+\b")


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.strip().split())


def split_sentences(text: str) -> List[str]:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return []
    parts = _SENTENCE_RE.split(cleaned)
    return [part.strip() for part in parts if part.strip()]


def estimate_seconds(text: str, words_per_second: float) -> int:
    words = len(_WORD_RE.findall(text))
    if words == 0:
        return 0
    seconds = int(round(words / words_per_second))
    return max(1, seconds)


def _figure_to_text(chapter: Chapter) -> List[str]:
    parts: List[str] = []
    for fig in chapter.figure_narration:
        sentences = [fig.description]
        if fig.axes:
            sentences.append(f"Axes: {fig.axes}.")
        if fig.trend:
            sentences.append(f"Trend: {fig.trend}.")
        if fig.significance:
            sentences.append(f"Significance: {fig.significance}.")
        parts.append(" ".join(sentences))
    return parts


def _spoken_math_lines(chapter: Chapter) -> List[str]:
    lines: List[str] = []
    for item in chapter.spoken_math:
        if item.spoken:
            lines.append(item.spoken)
        if item.intuition:
            lines.append(item.intuition)
    return [line.strip() for line in lines if line and line.strip()]


def _iter_sections(script: LectureScript) -> Iterable[Tuple[str, str, List[str]]]:
    for chapter in script.chapters:
        text_parts = [chapter.narration]
        text_parts.extend(_figure_to_text(chapter))
        narration = _normalize_whitespace(" ".join([p for p in text_parts if p]))
        yield chapter.name, narration, _spoken_math_lines(chapter)
    if script.final_recap:
        recap = _normalize_whitespace(script.final_recap)
        if recap:
            yield "Recap", recap, []


def generate_lecture_chunks(
    script: LectureScript,
    target_seconds: int | None = None,
    words_per_second: float | None = None,
) -> List[LectureChunk]:
    target = target_seconds or settings.chunk_target_seconds
    wps = words_per_second or settings.chunk_words_per_second
    chunks: List[LectureChunk] = []
    chunk_id = 0

    for section_name, section_text, math_lines in _iter_sections(script):
        if section_text:
            sentences = split_sentences(section_text)
            current: List[str] = []
            for sentence in sentences:
                current.append(sentence)
                if estimate_seconds(" ".join(current), wps) >= target:
                    text = _normalize_whitespace(" ".join(current))
                    approx = estimate_seconds(text, wps)
                    chunks.append(
                        LectureChunk(
                            chunk_id=chunk_id,
                            approx_seconds=approx,
                            text=text,
                            spoken_math=None,
                            section_name=section_name,
                            source_refs=None,
                        )
                    )
                    chunk_id += 1
                    current = []
            if current:
                text = _normalize_whitespace(" ".join(current))
                approx = estimate_seconds(text, wps)
                chunks.append(
                    LectureChunk(
                        chunk_id=chunk_id,
                        approx_seconds=approx,
                        text=text,
                        spoken_math=None,
                        section_name=section_name,
                        source_refs=None,
                    )
                )
                chunk_id += 1

        if math_lines:
            math_text = _normalize_whitespace(" ".join(math_lines))
            if math_text:
                approx = estimate_seconds(math_text, wps)
                chunks.append(
                    LectureChunk(
                        chunk_id=chunk_id,
                        approx_seconds=approx,
                        text=math_text,
                        spoken_math=math_lines,
                        section_name=section_name,
                        source_refs=None,
                    )
                )
                chunk_id += 1

    return chunks


def write_chunks(path: Path, chunks: List[LectureChunk]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [chunk.model_dump() for chunk in chunks]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_chunks(path: Path) -> List[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def get_chunk_by_index(chunks: List[dict], index: int) -> dict:
    if index < 0 or index >= len(chunks):
        raise IndexError("Chunk index out of range")
    return chunks[index]


def build_context_text(chunks: List[dict], index: int, window_seconds: int) -> Tuple[str, int]:
    if index <= 0:
        return "", 0
    total = 0
    collected: List[str] = []
    cursor = index - 1
    while cursor >= 0 and total < window_seconds:
        chunk = chunks[cursor]
        text = chunk.get("text") or ""
        if text:
            collected.append(text)
        total += int(chunk.get("approx_seconds") or 0)
        cursor -= 1
    collected.reverse()
    return "\n".join(collected).strip(), total
