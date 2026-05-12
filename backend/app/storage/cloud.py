"""Cloud storage placeholder – not implemented for MVP."""

from __future__ import annotations

from pathlib import Path

from app.storage.base import StorageBackend


class CloudStorage(StorageBackend):
    """Placeholder for S3 / GCS / R2 storage.

    Implement in Phase 2 when moving beyond local development.
    """

    def __init__(self, provider: str, bucket: str, **kwargs: object):
        self.provider = provider
        self.bucket = bucket
        raise NotImplementedError(
            f"Cloud storage ({provider}) is not yet implemented. "
            "Use STORAGE_BACKEND=local for MVP."
        )

    async def save(self, key: str, data: bytes) -> str:
        raise NotImplementedError

    async def save_file(self, key: str, source_path: Path) -> str:
        raise NotImplementedError

    async def get(self, key: str) -> bytes:
        raise NotImplementedError

    async def get_path(self, key: str) -> Path:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError

    def get_url(self, key: str) -> str:
        raise NotImplementedError
