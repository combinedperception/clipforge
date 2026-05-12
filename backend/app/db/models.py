"""SQLAlchemy ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    """Shared base for all ORM models."""
    type_annotation_map = {
        dict: JSON,
    }


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    original_filename: Mapped[str] = mapped_column(String(512))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(
        Enum(
            "pending", "uploaded", "extracting_audio", "transcribing",
            "segmenting", "selecting_clips", "generating_edit_plans",
            "rendering", "generating_metadata", "ready_for_review",
            "approved", "failed",
            name="job_status",
        ),
        default="pending",
    )
    current_stage_message: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    transcript_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    edit_plans_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    clips: Mapped[list[CandidateClip]] = relationship(back_populates="job", cascade="all, delete-orphan")


class CandidateClip(Base):
    __tablename__ = "candidate_clips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("video_jobs.id", ondelete="CASCADE"))
    clip_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", name="clip_approval_status"),
        default="pending",
    )
    edit_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    transcript_snippet: Mapped[str] = mapped_column(Text, default="")
    rendered_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    start_time: Mapped[float] = mapped_column(Float, default=0)
    end_time: Mapped[float] = mapped_column(Float, default=0)
    score_overall: Mapped[float] = mapped_column(Float, default=0)
    is_favorite: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    job: Mapped[VideoJob] = relationship(back_populates="clips")


class BrandProfileModel(Base):
    __tablename__ = "brand_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="default")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
