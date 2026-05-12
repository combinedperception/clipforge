"""Local filesystem storage implementation."""

from __future__ import annotations

import shutil
from pathlib import Path

import aiofiles

from app.core.errors import StorageError
from app.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    """Store files on the local filesystem."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        resolved = (self.base_dir / key).resolve()
        # Prevent path traversal
        if not str(resolved).startswith(str(self.base_dir)):
            raise StorageError("resolve", key, "path traversal detected")
        return resolved

    async def save(self, key: str, data: bytes) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
        return key

    async def save_file(self, key: str, source_path: Path) -> str:
        dest = self._resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest)
        return key

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise StorageError("get", key, "file not found")
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def get_path(self, key: str) -> Path:
        path = self._resolve(key)
        if not path.exists():
            raise StorageError("get_path", key, "file not found")
        return path

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    async def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def get_url(self, key: str) -> str:
        return f"/storage/{key}"
