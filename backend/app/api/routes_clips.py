"""Clip action endpoints: approve, reject, regenerate, render, download."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ClipNotFoundError
from app.core.logging import get_logger
from app.db.repositories import ClipRepository
from app.db.session import get_db
from app.schemas.clip import CandidateClipResponse, ClipActionResponse, ClipMetadataUpdate, EditPlan

router = APIRouter(prefix="/api/clips", tags=["clips"])
logger = get_logger(__name__)


@router.post("/{clip_id}/approve", response_model=ClipActionResponse)
async def approve_clip(
    clip_id: str,
    db: AsyncSession = Depends(get_db),
) -> ClipActionResponse:
    """Mark a clip as approved."""
    repo = ClipRepository(db)
    clip = await repo.update_status(clip_id, "approved")
    if clip is None:
        raise ClipNotFoundError(clip_id)

    return ClipActionResponse(
        clip_id=clip_id,
        action="approve",
        success=True,
        message="Clip approved successfully.",
    )


@router.post("/{clip_id}/reject", response_model=ClipActionResponse)
async def reject_clip(
    clip_id: str,
    db: AsyncSession = Depends(get_db),
) -> ClipActionResponse:
    """Mark a clip as rejected."""
    repo = ClipRepository(db)
    clip = await repo.update_status(clip_id, "rejected")
    if clip is None:
        raise ClipNotFoundError(clip_id)

    return ClipActionResponse(
        clip_id=clip_id,
        action="reject",
        success=True,
        message="Clip rejected.",
    )


@router.post("/{clip_id}/regenerate-metadata", response_model=ClipActionResponse)
async def regenerate_metadata(
    clip_id: str,
    db: AsyncSession = Depends(get_db),
) -> ClipActionResponse:
    """Regenerate metadata (title, description, hashtags) for a clip."""
    repo = ClipRepository(db)
    clip = await repo.get(clip_id)
    if clip is None:
        raise ClipNotFoundError(clip_id)

    try:
        from app.workers.tasks import regenerate_clip_metadata
        regenerate_clip_metadata.delay(clip_id)
    except Exception as exc:
        logger.warning("task_dispatch_failed", clip_id=clip_id, task="regenerate_metadata", error=str(exc))

    return ClipActionResponse(
        clip_id=clip_id,
        action="regenerate_metadata",
        success=True,
        message="Metadata regeneration started.",
    )


@router.post("/{clip_id}/render", response_model=ClipActionResponse)
async def rerender_clip(
    clip_id: str,
    db: AsyncSession = Depends(get_db),
) -> ClipActionResponse:
    """Re-render a clip from its existing edit plan."""
    repo = ClipRepository(db)
    clip = await repo.get(clip_id)
    if clip is None:
        raise ClipNotFoundError(clip_id)

    try:
        from app.workers.tasks import rerender_clip as rerender_task
        rerender_task.delay(clip_id)
    except Exception as exc:
        logger.warning("task_dispatch_failed", clip_id=clip_id, task="rerender", error=str(exc))

    return ClipActionResponse(
        clip_id=clip_id,
        action="render",
        success=True,
        message="Re-render started.",
    )


@router.post("/{clip_id}/favorite", response_model=ClipActionResponse)
async def toggle_favorite(
    clip_id: str,
    db: AsyncSession = Depends(get_db),
) -> ClipActionResponse:
    """Toggle the favorite flag on a clip."""
    repo = ClipRepository(db)
    clip = await repo.toggle_favorite(clip_id)
    if clip is None:
        raise ClipNotFoundError(clip_id)

    return ClipActionResponse(
        clip_id=clip_id,
        action="favorite",
        success=True,
        message=f"Clip {'favorited' if clip.is_favorite else 'unfavorited'}.",
    )


@router.patch("/{clip_id}/metadata", response_model=CandidateClipResponse)
async def update_clip_metadata(
    clip_id: str,
    body: ClipMetadataUpdate,
    db: AsyncSession = Depends(get_db),
) -> CandidateClipResponse:
    """Update the publish metadata (title, description, hashtags) for a clip."""
    repo = ClipRepository(db)
    clip = await repo.update_metadata(clip_id, body.title, body.description, body.hashtags)
    if clip is None:
        raise ClipNotFoundError(clip_id)

    clip_id_on_disk = clip.edit_plan.get("clip_id", clip.id) if clip.edit_plan else clip.id
    return CandidateClipResponse(
        id=clip.id,
        job_id=clip.job_id,
        clip_index=clip.clip_index,
        status=clip.status,
        edit_plan=EditPlan.model_validate(clip.edit_plan),
        rendered_url=(
            f"/storage/jobs/{clip.job_id}/clips/{clip_id_on_disk}.mp4"
            if clip.rendered_path
            else None
        ),
        transcript_snippet=clip.transcript_snippet or "",
        start_time=clip.start_time,
        end_time=clip.end_time,
        duration=clip.end_time - clip.start_time,
        score_overall=clip.score_overall,
        is_favorite=clip.is_favorite,
        created_at=clip.created_at,
        updated_at=clip.updated_at,
    )


@router.get("/{clip_id}/download")
async def download_clip(
    clip_id: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Download the rendered clip file."""
    settings = get_settings()
    repo = ClipRepository(db)
    clip = await repo.get(clip_id)
    if clip is None:
        raise ClipNotFoundError(clip_id)

    if not clip.rendered_path:
        raise ClipNotFoundError(clip_id)

    # Resolve and validate the path stays within the storage directory
    storage_root = Path(settings.local_storage_path).resolve()
    file_path = Path(clip.rendered_path).resolve()
    if not str(file_path).startswith(str(storage_root)):
        logger.error("path_traversal_blocked", clip_id=clip_id, path=str(file_path))
        raise ClipNotFoundError(clip_id)

    if not file_path.exists():
        raise ClipNotFoundError(clip_id)

    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=f"clip_{clip.clip_index}.mp4",
    )
