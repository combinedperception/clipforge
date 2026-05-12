"""Job listing and detail endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import JobNotFoundError
from app.db.repositories import ClipRepository, JobRepository
from app.db.session import get_db
from app.schemas.clip import CandidateClipResponse, EditPlan
from app.schemas.video import VideoJobDetail, VideoJobListResponse, VideoJobResponse, VideoUploadParams

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=VideoJobListResponse)
async def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> VideoJobListResponse:
    """List all video processing jobs with pagination."""
    repo = JobRepository(db)
    jobs, total = await repo.list_jobs(page=page, page_size=page_size)

    return VideoJobListResponse(
        jobs=[
            VideoJobResponse(
                id=j.id,
                original_filename=j.original_filename,
                status=j.status,
                current_stage_message=j.current_stage_message or "",
                error_message=j.error_message,
                clip_count=len(j.clips) if j.clips else 0,
                created_at=j.created_at,
                updated_at=j.updated_at,
            )
            for j in jobs
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{job_id}", response_model=VideoJobDetail)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> VideoJobDetail:
    """Get detailed information about a specific job."""
    repo = JobRepository(db)
    job = await repo.get(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    return VideoJobDetail(
        id=job.id,
        original_filename=job.original_filename,
        status=job.status,
        current_stage_message=job.current_stage_message or "",
        error_message=job.error_message,
        clip_count=len(job.clips) if job.clips else 0,
        created_at=job.created_at,
        updated_at=job.updated_at,
        file_size_bytes=job.file_size_bytes,
        storage_path=job.storage_path,
        params=VideoUploadParams.model_validate(job.params) if job.params else VideoUploadParams(),
        transcript_path=job.transcript_path,
        edit_plans_path=job.edit_plans_path,
    )


@router.get("/{job_id}/clips", response_model=list[CandidateClipResponse])
async def list_job_clips(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[CandidateClipResponse]:
    """List all generated clips for a job."""
    # Verify job exists
    job_repo = JobRepository(db)
    job = await job_repo.get(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    clip_repo = ClipRepository(db)
    clips = await clip_repo.list_by_job(job_id)

    result = []
    for c in clips:
        # The rendered file is named after edit_plan.clip_id, not the DB row id.
        clip_id_on_disk = c.edit_plan.get("clip_id", c.id) if c.edit_plan else c.id
        result.append(
            CandidateClipResponse(
                id=c.id,
                job_id=c.job_id,
                clip_index=c.clip_index,
                status=c.status,
                edit_plan=EditPlan.model_validate(c.edit_plan),
                rendered_url=(
                    f"/storage/jobs/{job_id}/clips/{clip_id_on_disk}.mp4"
                    if c.rendered_path
                    else None
                ),
                transcript_snippet=c.transcript_snippet or "",
                start_time=c.start_time,
                end_time=c.end_time,
                duration=c.end_time - c.start_time,
                score_overall=c.score_overall,
                is_favorite=c.is_favorite,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )
    return result
