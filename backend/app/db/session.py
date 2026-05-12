"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def _build_engine():
    """Create and cache the async engine (built on first call, not at import)."""
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
    )


@lru_cache
def _build_session_factory():
    return async_sessionmaker(
        _build_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency – yields an async session."""
    factory = _build_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
