from __future__ import annotations

from pathlib import Path
from typing import BinaryIO


class BaseStorage:
    def save_upload(self, file_obj: BinaryIO, dest: Path) -> None:
        raise NotImplementedError

    def write_text(self, dest: Path, data: str) -> None:
        raise NotImplementedError

    def write_bytes(self, dest: Path, data: bytes) -> None:
        raise NotImplementedError

    def read_bytes(self, src: Path) -> bytes:
        raise NotImplementedError

    def exists(self, path: Path) -> bool:
        raise NotImplementedError

    def copy(self, src: Path, dest: Path) -> None:
        raise NotImplementedError
