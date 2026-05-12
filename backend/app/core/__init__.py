"""Application configuration via environment variables."""

from __future__ import annotations

import enum
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageBackendType(str, enum.Enum):
    LOCAL = "local"
    S3 = "s3"
    GCS = "gcs"
    R2 = "r2"


class Settings(BaseSettings):
    """Central configuration – all values come from env vars or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
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
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # ── YouTube (Phase 2) ─────────────────────────────────
    youtube_client_id: str = ""
    youtube_client_secret: str = ""

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
