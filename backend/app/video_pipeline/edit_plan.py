"""Edit plan construction from agent output."""

from __future__ import annotations

import uuid

from app.schemas.clip import (
    AudioSettings,
    CaptionStyle,
    ClipScore,
    EditPlan,
    PublishMetadata,
)
from app.schemas.enums import TargetPlatform, VideoFormat
from app.schemas.transcript import TranscriptSegment


def build_edit_plan(
    segment: TranscriptSegment,
    score: ClipScore,
    source_video_id: str,
    clip_index: int,
    target_platform: TargetPlatform = TargetPlatform.YOUTUBE_SHORTS,
    caption_style: CaptionStyle | None = None,
) -> EditPlan:
    """Build a structured EditPlan from a scored segment.

    In the agentic workflow, the LLM produces richer plans.
    This is a deterministic builder for the pipeline fallback.
    """
    clip_id = f"clip_{uuid.uuid4().hex[:8]}"

    # Extract first sentence as hook
    sentences = segment.text.split(". ")
    hook = sentences[0] if sentences else segment.text[:100]

    return EditPlan(
        clip_id=clip_id,
        source_video_id=source_video_id,
        start_time=segment.start_time,
        end_time=segment.end_time,
        format=VideoFormat.VERTICAL_9_16,
        target_platform=target_platform,
        hook=hook,
        selection_reason=f"Candidate #{clip_index + 1} selected by scoring pipeline.",
        score=score,
        caption_style=caption_style or CaptionStyle(),
        visual_edits=[],
        audio=AudioSettings(normalize=True, noise_reduction=False),
        metadata=PublishMetadata(),
    )
