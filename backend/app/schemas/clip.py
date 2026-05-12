"""Clip, edit plan, and scoring schemas – central data contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import (
    CaptionType,
    ClipApprovalStatus,
    TargetPlatform,
    VideoFormat,
    VisualEditType,
)


# ── Scoring ───────────────────────────────────────────────


class ClipScore(BaseModel):
    """Quality scores for a candidate clip."""

    hook_strength: float = Field(ge=0, le=1)
    standalone_clarity: float = Field(ge=0, le=1)
    insight_value: float = Field(ge=0, le=1)
    virality_potential: float = Field(ge=0, le=1)
    audience_fit: float = Field(ge=0, le=1)
    overall: float = Field(ge=0, le=1)


# ── Caption Style ─────────────────────────────────────────


class CaptionStyle(BaseModel):
    """Visual styling for burned-in captions."""

    type: CaptionType = CaptionType.BASIC
    font: str = "Inter"
    position: str = "bottom"
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#2DB8A0"
    background_color: str = "#111827"


# ── Visual Edits ──────────────────────────────────────────


class VisualEdit(BaseModel):
    """A single visual edit instruction (zoom, CTA bar, etc.)."""

    type: VisualEditType
    timestamp: float | None = None
    duration: float | None = None
    intensity: str = "medium"
    text: str = ""
    start_time: float | None = None
    end_time: float | None = None


# ── Audio Settings ────────────────────────────────────────


class AudioSettings(BaseModel):
    """Audio processing settings."""

    normalize: bool = True
    noise_reduction: bool = False


# ── Publish Metadata ─────────────────────────────────────


class PublishMetadata(BaseModel):
    """Metadata for publishing a clip to social platforms."""

    title: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)


# ── Edit Plan ─────────────────────────────────────────────


class EditPlan(BaseModel):
    """Structured edit plan produced by the AI agent and executed by FFmpeg.

    This is the core contract between the agentic layer and the
    deterministic rendering pipeline.
    """

    clip_id: str
    source_video_id: str
    start_time: float = Field(ge=0)
    end_time: float = Field(ge=0)
    format: VideoFormat = VideoFormat.VERTICAL_9_16
    target_platform: TargetPlatform = TargetPlatform.YOUTUBE_SHORTS
    hook: str = ""
    selection_reason: str = ""
    score: ClipScore
    caption_style: CaptionStyle = Field(default_factory=CaptionStyle)
    visual_edits: list[VisualEdit] = Field(default_factory=list)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    metadata: PublishMetadata = Field(default_factory=PublishMetadata)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


# ── Candidate Clip Response ───────────────────────────────


class CandidateClipResponse(BaseModel):
    """API response for a generated clip."""

    id: str
    job_id: str
    clip_index: int
    status: ClipApprovalStatus = ClipApprovalStatus.PENDING
    edit_plan: EditPlan
    rendered_url: str | None = None
    transcript_snippet: str = ""
    start_time: float = 0
    end_time: float = 0
    duration: float = 0
    score_overall: float = 0
    is_favorite: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClipMetadataUpdate(BaseModel):
    """Partial update for clip publish metadata."""

    title: str | None = None
    description: str | None = None
    hashtags: list[str] | None = None


class ClipActionResponse(BaseModel):
    """Response after an action on a clip (approve, reject, etc.)."""

    clip_id: str
    action: str
    success: bool
    message: str = ""
