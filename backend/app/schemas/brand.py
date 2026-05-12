"""Brand profile schema."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.enums import CaptionType, TargetPlatform


class PlatformPreset(BaseModel):
    """Per-platform defaults."""

    platform: TargetPlatform
    clip_duration_min: int = 30
    clip_duration_max: int = 60
    caption_type: CaptionType = CaptionType.BASIC
    default_hashtags: list[str] = Field(default_factory=list)


class BrandProfile(BaseModel):
    """User's brand settings applied to all generated clips."""

    id: str = "default"
    brand_name: str = "ClipForge AI"
    primary_color: str = "#2DB8A0"
    secondary_color: str = "#111827"
    accent_color: str = "#6366F1"
    font: str = "Inter"
    caption_type: CaptionType = CaptionType.BASIC
    caption_position: str = "bottom"
    caption_primary_color: str = "#FFFFFF"
    caption_highlight_color: str = "#2DB8A0"
    caption_background_color: str = "#111827"
    cta_text: str = ""
    logo_url: str = ""
    outro_text: str = ""
    platform_presets: list[PlatformPreset] = Field(default_factory=list)


class BrandProfileUpdate(BaseModel):
    """Partial update for brand profile."""

    brand_name: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_color: str | None = None
    font: str | None = None
    caption_type: CaptionType | None = None
    caption_position: str | None = None
    caption_primary_color: str | None = None
    caption_highlight_color: str | None = None
    caption_background_color: str | None = None
    cta_text: str | None = None
    logo_url: str | None = None
    outro_text: str | None = None
    platform_presets: list[PlatformPreset] | None = None
