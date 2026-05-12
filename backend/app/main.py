"""ClipForge AI – FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_brand import router as brand_router
from app.api.routes_clips import router as clips_router
from app.api.routes_jobs import router as jobs_router
from app.api.routes_upload import router as upload_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import get_logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    setup_logging()
    logger = get_logger(__name__)
    settings = get_settings()

    # Ensure storage directory exists
    Path(settings.local_storage_path).mkdir(parents=True, exist_ok=True)

    # Create database tables (for SQLite dev mode)
    if "sqlite" in settings.database_url:
        from app.db.models import Base
        from app.db.session import _build_engine

        async with _build_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("database_initialized", backend="sqlite")

    logger.info("app_started", app_name=settings.app_name)
    yield
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="AI-assisted video editing – transform long-form video into polished short-form clips.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS – allow frontend dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Error handlers
    register_error_handlers(app)

    # API routes
    app.include_router(upload_router)
    app.include_router(jobs_router)
    app.include_router(clips_router)
    app.include_router(brand_router)

    # Health check
    @app.get("/api/health", tags=["health"])
    async def health_check() -> dict:
        return {"status": "healthy", "app": settings.app_name, "version": "0.1.0"}

    # Serve stored files (for local dev – in production use nginx/CDN)
    storage_path = Path(settings.local_storage_path)
    if storage_path.exists():
        app.mount("/storage", StaticFiles(directory=str(storage_path)), name="storage")

    return app


# Application instance used by uvicorn
app = create_app()
