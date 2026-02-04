from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

import httpx
from openai import OpenAI

from app.chunking import generate_lecture_chunks, write_chunks
from app.config import settings
from app.pipeline.analyze_pdf import analyze_pdf_chunks
from app.pipeline.script_writer import merge_chunks_to_script


def _ensure_dirs() -> None:
    for path in [settings.data_dir, settings.scripts_dir, settings.chunks_dir]:
        Path(path).mkdir(parents=True, exist_ok=True)


def _iter_pdfs(path: Path):
    if path.is_file() and path.suffix.lower() == ".pdf":
        yield path
        return
    if path.is_dir():
        yield from path.rglob("*.pdf")


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a PDF locally and upload lecture data.")
    parser.add_argument("path", type=str, help="Path to a PDF or a folder of PDFs")
    parser.add_argument("--server", help="Server base URL, e.g. https://example.com")
    parser.add_argument("--lecture-id", default=None, help="Optional lecture ID to reuse")
    parser.add_argument("--title", default=None, help="Optional title override")
    parser.add_argument(
        "--token",
        default=os.environ.get("UPLOAD_TOKEN"),
        help="Upload token (or set UPLOAD_TOKEN in env)",
    )
    parser.add_argument("--store-only", action="store_true", help="Skip upload; only write local files")
    args = parser.parse_args()

    input_path = Path(args.path)
    if not input_path.exists():
        raise SystemExit(f"Path not found: {input_path}")
    if not args.store_only and not args.server:
        raise SystemExit("--server is required unless --store-only is set")

    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY not set")

    _ensure_dirs()
    client = OpenAI(api_key=settings.openai_api_key)
    server_url = args.server.rstrip("/") if args.server else None
    headers = {"X-Upload-Token": args.token} if args.token else {}

    processed = 0
    for pdf_path in _iter_pdfs(input_path):
        lecture_id = args.lecture_id or uuid.uuid4().hex
        title_hint = args.title or pdf_path.stem

        chunks = analyze_pdf_chunks(client, pdf_path)
        script = merge_chunks_to_script(client, [c.data for c in chunks], title_hint)
        lecture_chunks = generate_lecture_chunks(script)

        script_path = settings.scripts_dir / f"{lecture_id}_lecture_script.json"
        script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
        chunks_path = settings.chunks_dir / f"{lecture_id}.json"
        write_chunks(chunks_path, lecture_chunks)

        payload = {
            "lecture_id": lecture_id,
            "title": args.title or script.title,
            "source_filename": pdf_path.name,
            "lecture_script": script.model_dump(),
            "chunks": [chunk.model_dump() for chunk in lecture_chunks],
        }

        if args.store_only:
            print(f"Stored lecture {lecture_id} locally.")
            print(f"Script: {script_path}")
            print(f"Chunks: {chunks_path}")
            processed += 1
            continue

        resp = httpx.post(
            f"{server_url}/lectures/preprocessed",
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        print(f"Uploaded lecture {lecture_id} to {server_url}")
        processed += 1

    if processed == 0:
        raise SystemExit("No PDFs found to process.")


if __name__ == "__main__":
    main()
