"""Video and job schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import JobStatus, TargetPlatform, Tone


class VideoUploadParams(BaseModel):
    """Optional parameters submitted alongside a video upload."""

    target_audience: str = ""
    desired_clip_count: int = Field(default=5, ge=1, le=20)
    clip_duration_min: int = Field(default=30, ge=10, le=120)
    clip_duration_max: int = Field(default=60, ge=15, le=180)
    target_platforms: list[TargetPlatform] = Field(default_factory=lambda: [TargetPlatform.YOUTUBE_SHORTS])
    tone: Tone = Tone.PROFESSIONAL


class VideoJobCreate(BaseModel):
    """Internal representation when creating a new job."""

    original_filename: str
    file_size_bytes: int
    storage_path: str
    params: VideoUploadParams = Field(default_factory=VideoUploadParams)


class VideoJobResponse(BaseModel):
    """API response for a single job."""

    id: str
    original_filename: str
    status: JobStatus
    current_stage_message: str = ""
    error_message: str | None = None
    clip_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VideoJobDetail(VideoJobResponse):
    """Extended job detail including processing params."""

    file_size_bytes: int
    storage_path: str
    params: VideoUploadParams
    transcript_path: str | None = None
    edit_plans_path: str | None = None

    model_config = {"from_attributes": True}


class VideoJobListResponse(BaseModel):
    """Paginated list of jobs."""

    jobs: list[VideoJobResponse]
    total: int
    page: int
    page_size: int
