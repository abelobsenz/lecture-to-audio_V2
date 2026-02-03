from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from app.storage.base import BaseStorage


class LocalStorage(BaseStorage):
    def save_upload(self, file_obj: BinaryIO, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            shutil.copyfileobj(file_obj, f)

    def write_text(self, dest: Path, data: str) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(data, encoding="utf-8")

    def write_bytes(self, dest: Path, data: bytes) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def read_bytes(self, src: Path) -> bytes:
        return src.read_bytes()

    def exists(self, path: Path) -> bool:
        return path.exists()

    def copy(self, src: Path, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
