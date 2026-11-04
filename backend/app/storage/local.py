"""Local-disk storage adapter (development)."""

import asyncio
import contextlib
import os
import re
import uuid
from pathlib import Path

from app.storage.base import InvalidStorageKeyError, StorageNotFoundError

_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}/[0-9a-f]{32}$")


class LocalStorage:
    """Stores objects as files under ``root``.

    The root must not be served by any web server. Keys are validated against a
    strict pattern and the resolved path is re-checked to stay inside the root, so
    a malicious key cannot escape it. Files are written atomically and are never
    executed or opened by anything other than this class.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        if not _KEY_PATTERN.fullmatch(key):
            raise InvalidStorageKeyError("Invalid storage key")
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise InvalidStorageKeyError("Invalid storage key")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        await asyncio.to_thread(self._write, path, data)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{uuid.uuid4().hex}.tmp")
        try:
            with open(temp, "xb") as handle:
                handle.write(data)
            os.replace(temp, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temp.unlink()

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise StorageNotFoundError("Object not found") from None

    async def delete(self, key: str) -> None:
        path = self._path(key)
        with contextlib.suppress(FileNotFoundError):
            await asyncio.to_thread(path.unlink)
