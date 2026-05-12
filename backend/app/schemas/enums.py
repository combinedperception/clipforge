"""Shared enums used across schemas."""

from __future__ import annotations

import enum


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    SEGMENTING = "segmenting"
    SELECTING_CLIPS = "selecting_clips"
    GENERATING_EDIT_PLANS = "generating_edit_plans"
    RENDERING = "rendering"
    GENERATING_METADATA = "generating_metadata"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    FAILED = "failed"


class ClipApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TargetPlatform(str, enum.Enum):
    YOUTUBE_SHORTS = "youtube_shorts"
    TIKTOK = "tiktok"
    INSTAGRAM_REELS = "instagram_reels"
    LINKEDIN = "linkedin"


class VideoFormat(str, enum.Enum):
    VERTICAL_9_16 = "vertical_9_16"
    HORIZONTAL_16_9 = "horizontal_16_9"
    SQUARE_1_1 = "square_1_1"


class Tone(str, enum.Enum):
    EDUCATIONAL = "educational"
    ENERGETIC = "energetic"
    PROFESSIONAL = "professional"
    HUMOROUS = "humorous"


class CaptionType(str, enum.Enum):
    BASIC = "basic"
    KARAOKE = "karaoke"
    ANIMATED = "animated"


class VisualEditType(str, enum.Enum):
    ZOOM = "zoom"
    CTA_BAR = "cta_bar"
    TEXT_OVERLAY = "text_overlay"
    TRANSITION = "transition"
