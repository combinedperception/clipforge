"""Video upload endpoint."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import InvalidVideoError
from app.core.logging import get_logger
from app.db.repositories import JobRepository
from app.db.session import get_db
from app.schemas.enums import TargetPlatform, Tone
from app.schemas.video import VideoJobCreate, VideoJobResponse, VideoUploadParams
from app.video_pipeline.ingest import validate_video_file

router = APIRouter(prefix="/api/videos", tags=["upload"])
logger = get_logger(__name__)

# Stream chunk size for large file uploads (64 KB)
_UPLOAD_CHUNK_SIZE = 64 * 1024


@router.post("/upload", response_model=VideoJobResponse, status_code=201)
async def upload_video(
    file: UploadFile = File(...),
    target_audience: str = Form(""),
    desired_clip_count: int = Form(5),
    clip_duration_min: int = Form(30),
    clip_duration_max: int = Form(60),
    target_platforms: str = Form("youtube_shorts"),
    tone: str = Form("professional"),
    db: AsyncSession = Depends(get_db),
) -> VideoJobResponse:
    """Upload a video file and create a processing job.

    The video is validated, streamed to disk, and a background
    processing task is dispatched via Celery.
    """
    settings = get_settings()

    # Validate filename and content type before reading anything
    filename = file.filename or "unknown.mp4"
    validate_video_file(
        filename=filename,
        content_type=file.content_type,
        size_bytes=1,  # placeholder; real size checked after streaming
        max_size_bytes=settings.max_upload_size_bytes,
    )

    # Generate job ID and prepare storage directory
    job_id = uuid.uuid4().hex
    job_dir = Path(settings.local_storage_path) / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    source_path = job_dir / "source.mp4"

    # Stream file to disk to avoid loading the full file into memory
    file_size = 0
    try:
        with open(source_path, "wb") as dest:
            while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
                file_size += len(chunk)
                if file_size > settings.max_upload_size_bytes:
                    raise InvalidVideoError(
                        f"File size exceeds limit of {settings.max_upload_size_mb} MB."
                    )
                dest.write(chunk)
    except InvalidVideoError:
        # Clean up partial file on size violation
        source_path.unlink(missing_ok=True)
        raise

    if file_size == 0:
        source_path.unlink(missing_ok=True)
        raise InvalidVideoError("File is empty.")

    # Parse platforms
    platforms = [
        TargetPlatform(p.strip())
        for p in target_platforms.split(",")
        if p.strip() in [e.value for e in TargetPlatform]
    ] or [TargetPlatform.YOUTUBE_SHORTS]

    # Parse tone
    try:
        tone_enum = Tone(tone)
    except ValueError:
        tone_enum = Tone.PROFESSIONAL

    params = VideoUploadParams(
        target_audience=target_audience,
        desired_clip_count=desired_clip_count,
        clip_duration_min=clip_duration_min,
        clip_duration_max=clip_duration_max,
        target_platforms=platforms,
        tone=tone_enum,
    )

    storage_key = f"jobs/{job_id}/source.mp4"

    # Create DB record
    repo = JobRepository(db)
    job_data = VideoJobCreate(
        original_filename=filename,
        file_size_bytes=file_size,
        storage_path=storage_key,
        params=params,
    )
    job = await repo.create(job_data)

    # Override the auto-generated ID with our job_id
    job.id = job_id

    # Commit BEFORE dispatching the Celery task so the worker can find the row.
    # db.flush() only makes changes visible within this session; the actual
    # transaction is not committed until get_db() exits.  If the Celery worker
    # picks up the task before the commit, _update_job_status() updates zero
    # rows and the job stays stuck at "uploaded" forever.
    await db.commit()

    logger.info("upload_complete", job_id=job_id, filename=filename, size_bytes=file_size)

    # Dispatch background processing task
    try:
        from app.workers.tasks import process_video_job

        process_video_job.delay(job_id)
        logger.info("task_dispatched", job_id=job_id)
    except Exception as exc:
        error_msg = f"Failed to dispatch processing task: {exc}"
        logger.error("task_dispatch_failed", job_id=job_id, error=str(exc))
        # Mark the job as failed so the user sees the problem in the UI
        from sqlalchemy import update as sa_update
        from app.db.models import VideoJob
        from app.db.session import _build_session_factory

        async with _build_session_factory()() as err_session:
            await err_session.execute(
                sa_update(VideoJob)
                .where(VideoJob.id == job_id)
                .values(status="failed", error_message=error_msg)
            )
            await err_session.commit()

    return VideoJobResponse(
        id=job.id,
        original_filename=job.original_filename,
        status=job.status,
        current_stage_message="Video uploaded successfully. Processing will begin shortly.",
        clip_count=0,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
