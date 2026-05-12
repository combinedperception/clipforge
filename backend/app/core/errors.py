"""Custom exceptions and FastAPI error handlers."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class ClipForgeError(Exception):
    """Base exception for all ClipForge errors."""

    def __init__(self, message: str, status_code: int = 500, detail: str | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or message
        super().__init__(self.message)


class VideoNotFoundError(ClipForgeError):
    def __init__(self, video_id: str):
        super().__init__(f"Video not found: {video_id}", status_code=404)


class JobNotFoundError(ClipForgeError):
    def __init__(self, job_id: str):
        super().__init__(f"Job not found: {job_id}", status_code=404)


class ClipNotFoundError(ClipForgeError):
    def __init__(self, clip_id: str):
        super().__init__(f"Clip not found: {clip_id}", status_code=404)


class InvalidVideoError(ClipForgeError):
    def __init__(self, reason: str):
        super().__init__(f"Invalid video: {reason}", status_code=422)


class PipelineError(ClipForgeError):
    def __init__(self, stage: str, reason: str):
        super().__init__(f"Pipeline error at {stage}: {reason}", status_code=500)


class FFmpegError(ClipForgeError):
    def __init__(self, command: str, stderr: str):
        # Show the tail of stderr — the ffmpeg version banner fills the first
        # ~400 chars and the actual error message appears at the end.
        error_snippet = stderr[-500:] if len(stderr) > 500 else stderr
        super().__init__(
            f"FFmpeg error: {error_snippet}",
            status_code=500,
            detail=f"Command: {command}\nStderr: {stderr}",
        )


class StorageError(ClipForgeError):
    def __init__(self, operation: str, path: str, reason: str):
        super().__init__(f"Storage {operation} failed for {path}: {reason}", status_code=500)


def register_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(ClipForgeError)
    async def clipforge_error_handler(request: Request, exc: ClipForgeError) -> JSONResponse:
        logger.error(
            "application_error",
            error_type=type(exc).__name__,
            message=exc.message,
            status_code=exc.status_code,
            path=str(request.url),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": type(exc).__name__, "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error",
            error_type=type(exc).__name__,
            message=str(exc),
            path=str(request.url),
        )
        return JSONResponse(
            status_code=500,
            content={"error": "InternalServerError", "message": "An unexpected error occurred."},
        )
