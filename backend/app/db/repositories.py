"""Database CRUD operations (repository pattern)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import BrandProfileModel, CandidateClip, VideoJob
from app.schemas.brand import BrandProfile
from app.schemas.video import VideoJobCreate


class JobRepository:
    """CRUD operations for VideoJob."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: VideoJobCreate) -> VideoJob:
        job = VideoJob(
            original_filename=data.original_filename,
            file_size_bytes=data.file_size_bytes,
            storage_path=data.storage_path,
            status="uploaded",
            params=data.params.model_dump(),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: str) -> VideoJob | None:
        result = await self.session.execute(
            select(VideoJob)
            .options(selectinload(VideoJob.clips))
            .where(VideoJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_jobs(self, page: int = 1, page_size: int = 20) -> tuple[list[VideoJob], int]:
        offset = (page - 1) * page_size

        count_result = await self.session.execute(select(func.count(VideoJob.id)))
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(VideoJob)
            .options(selectinload(VideoJob.clips))
            .order_by(VideoJob.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def update_status(
        self, job_id: str, status: str, message: str = "", error: str | None = None
    ) -> VideoJob | None:
        job = await self.get(job_id)
        if job is None:
            return None
        job.status = status
        job.current_stage_message = message
        if error is not None:
            job.error_message = error
        await self.session.flush()
        return job


class ClipRepository:
    """CRUD operations for CandidateClip."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, clip: CandidateClip) -> CandidateClip:
        self.session.add(clip)
        await self.session.flush()
        return clip

    async def get(self, clip_id: str) -> CandidateClip | None:
        result = await self.session.execute(
            select(CandidateClip).where(CandidateClip.id == clip_id)
        )
        return result.scalar_one_or_none()

    async def list_by_job(self, job_id: str) -> list[CandidateClip]:
        result = await self.session.execute(
            select(CandidateClip)
            .where(CandidateClip.job_id == job_id)
            .order_by(CandidateClip.clip_index)
        )
        return list(result.scalars().all())

    async def update_status(self, clip_id: str, status: str) -> CandidateClip | None:
        clip = await self.get(clip_id)
        if clip is None:
            return None
        clip.status = status
        await self.session.flush()
        return clip

    async def toggle_favorite(self, clip_id: str) -> CandidateClip | None:
        clip = await self.get(clip_id)
        if clip is None:
            return None
        clip.is_favorite = not clip.is_favorite
        await self.session.flush()
        return clip

    async def update_metadata(
        self, clip_id: str, title: str | None, description: str | None, hashtags: list[str] | None
    ) -> CandidateClip | None:
        clip = await self.get(clip_id)
        if clip is None:
            return None
        plan = dict(clip.edit_plan)
        metadata = dict(plan.get("metadata", {}))
        if title is not None:
            metadata["title"] = title
        if description is not None:
            metadata["description"] = description
        if hashtags is not None:
            metadata["hashtags"] = hashtags
        plan["metadata"] = metadata
        clip.edit_plan = plan
        await self.session.flush()
        return clip


class BrandRepository:
    """CRUD operations for BrandProfile."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, profile_id: str = "default") -> BrandProfile:
        result = await self.session.execute(
            select(BrandProfileModel).where(BrandProfileModel.id == profile_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return BrandProfile()
        return BrandProfile.model_validate(row.data)

    async def upsert(self, profile: BrandProfile) -> BrandProfile:
        result = await self.session.execute(
            select(BrandProfileModel).where(BrandProfileModel.id == profile.id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = BrandProfileModel(id=profile.id, data=profile.model_dump())
            self.session.add(row)
        else:
            row.data = profile.model_dump()
        await self.session.flush()
        return profile
