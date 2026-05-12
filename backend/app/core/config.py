"""Application configuration via environment variables."""

from __future__ import annotations

import enum
from pathlib import Path
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageBackendType(str, enum.Enum):
    LOCAL = "local"
    S3 = "s3"
    GCS = "gcs"
    R2 = "r2"


def _find_env_file() -> str:
    """Locate the .env file, checking CWD first, then parent directories."""
    cwd = Path.cwd()
    for directory in [cwd, *cwd.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return str(candidate)
        # Stop at the repo root (has a .git folder or pyproject.toml)
        if (directory / ".git").exists():
            break
    return ".env"  # fallback — pydantic-settings default


class Settings(BaseSettings):
    """Central configuration – all values come from env vars or .env file."""

    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────
    app_name: str = "ClipForge AI"
    debug: bool = False
    log_level: str = "INFO"

    # ── Database ──────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./clipforge.db"

    # ── Redis / Celery ────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── Storage ───────────────────────────────────────────
    storage_backend: StorageBackendType = StorageBackendType.LOCAL
    local_storage_path: Path = Path("./storage")

    # ── Upload limits ─────────────────────────────────────
    max_upload_size_mb: int = 500

    # ── AI / LLM ──────────────────────────────────────────
    openai_api_key: str = Field(default="", repr=False)
    openai_model: str = "gpt-4o"

    # ── YouTube (Phase 2) ─────────────────────────────────
    youtube_client_id: str = Field(default="", repr=False)
    youtube_client_secret: str = Field(default="", repr=False)

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
