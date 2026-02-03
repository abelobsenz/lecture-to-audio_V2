from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List

from openai import OpenAI

from app.config import settings
from app.schemas import LectureScript


def script_to_narration(script: LectureScript) -> str:
    parts: List[str] = []
    parts.append(f"Title: {script.title}.")
    for idx, ch in enumerate(script.chapters, start=1):
        parts.append(f"Chapter {idx}: {ch.name}.")
        parts.append(ch.narration.strip())
        if ch.spoken_math:
            parts.append("Let's pause for the key equations.")
            for sm in ch.spoken_math:
                parts.append(sm.spoken)
                if sm.intuition:
                    parts.append(sm.intuition)
        if ch.figure_narration:
            parts.append("Now a quick tour of the figures.")
            for fig in ch.figure_narration:
                parts.append(fig.description)
                if fig.trend:
                    parts.append(fig.trend)
                if fig.significance:
                    parts.append(fig.significance)
        parts.append("We'll pause briefly.")
    parts.append("Final recap.")
    parts.append(script.final_recap.strip())
    return "\n".join(parts)


def _chunk_text(text: str, max_chars: int = 3000) -> List[str]:
    chunks: List[str] = []
    buf: List[str] = []
    size = 0
    for line in text.splitlines():
        if size + len(line) + 1 > max_chars and buf:
            chunks.append("\n".join(buf))
            buf = []
            size = 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def _tts_call(client: OpenAI, text: str) -> bytes:
    base_kwargs = {
        "model": settings.openai_tts_model,
        "voice": settings.openai_tts_voice,
        "input": text,
    }
    try:
        response = client.audio.speech.create(
            **base_kwargs,
            response_format=settings.openai_tts_format,
        )
    except TypeError:
        response = client.audio.speech.create(
            **base_kwargs,
            format=settings.openai_tts_format,
        )
    return response.content


def _concat_with_ffmpeg(parts: List[Path], output_path: Path) -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    list_path = output_path.with_suffix(".txt")
    lines = [f"file '{p.as_posix()}'" for p in parts]
    list_path.write_text("\n".join(lines), encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    list_path.unlink(missing_ok=True)
    return result.returncode == 0


def _concat_mp3_binary(parts: List[Path], output_path: Path) -> None:
    with output_path.open("wb") as out_f:
        for p in parts:
            out_f.write(p.read_bytes())


def generate_audio(client: OpenAI, script: LectureScript, output_path: Path) -> Path:
    narration = script_to_narration(script)
    chunks = _chunk_text(narration)
    parts: List[Path] = []

    for idx, chunk in enumerate(chunks, start=1):
        audio_bytes = _tts_call(client, chunk)
        part_path = output_path.with_name(f"{output_path.stem}.part{idx}{output_path.suffix}")
        part_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(audio_bytes)
        parts.append(part_path)

    if len(parts) == 1:
        parts[0].replace(output_path)
        return output_path

    if _concat_with_ffmpeg(parts, output_path):
        for p in parts:
            p.unlink(missing_ok=True)
        return output_path

    if settings.openai_tts_format == "mp3":
        _concat_mp3_binary(parts, output_path)
        for p in parts:
            p.unlink(missing_ok=True)
        return output_path

    # Fallback: create playlist
    playlist = output_path.with_suffix(".m3u")
    playlist.write_text("\n".join([p.name for p in parts]), encoding="utf-8")
    return playlist
