"""Abstract storage backend interface."""

from __future__ import annotations

import abc
from pathlib import Path


class StorageBackend(abc.ABC):
    """Abstract interface for file storage.

    All paths are *relative* keys (e.g. "jobs/abc123/source.mp4").
    Implementations decide where to physically store the bytes.
    """

    @abc.abstractmethod
    async def save(self, key: str, data: bytes) -> str:
        """Save bytes and return the storage key."""

    @abc.abstractmethod
    async def save_file(self, key: str, source_path: Path) -> str:
        """Save a local file to storage and return the key."""

    @abc.abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve bytes by key."""

    @abc.abstractmethod
    async def get_path(self, key: str) -> Path:
        """Return a local filesystem path (download if needed)."""

    @abc.abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a stored object."""

    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        """Check whether a key exists."""

    @abc.abstractmethod
    def get_url(self, key: str) -> str:
        """Return a URL or file path suitable for serving to the frontend."""
