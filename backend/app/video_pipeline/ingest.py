"""Video ingestion – validation and initial storage."""

from __future__ import annotations

from pathlib import Path

from app.core.errors import InvalidVideoError
from app.core.logging import get_logger

logger = get_logger(__name__)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
}


def validate_video_file(filename: str, content_type: str | None, size_bytes: int, max_size_bytes: int) -> None:
    """Validate an uploaded video file before processing."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidVideoError(
            f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Allow application/octet-stream as a fallback — many HTTP clients
    # (curl, some browsers) send this for video files.  The file-extension
    # check above already limits accepted files.
    if (
        content_type
        and content_type not in ALLOWED_MIME_TYPES
        and content_type != "application/octet-stream"
    ):
        raise InvalidVideoError(
            f"Unsupported MIME type '{content_type}'. Expected a video file."
        )

    if size_bytes > max_size_bytes:
        max_mb = max_size_bytes / (1024 * 1024)
        raise InvalidVideoError(f"File size exceeds limit of {max_mb:.0f} MB.")

    if size_bytes == 0:
        raise InvalidVideoError("File is empty.")

    logger.info("video_validated", filename=filename, size_bytes=size_bytes)
