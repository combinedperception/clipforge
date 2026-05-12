"""Tests for Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.clip import (
    AudioSettings,
    CaptionStyle,
    ClipScore,
    EditPlan,
    PublishMetadata,
    VisualEdit,
)
from app.schemas.enums import (
    CaptionType,
    ClipApprovalStatus,
    JobStatus,
    TargetPlatform,
    VideoFormat,
    VisualEditType,
)
from app.schemas.transcript import Transcript, TranscriptSegment, WordTimestamp
from app.schemas.video import VideoUploadParams


class TestClipScore:
    def test_valid_scores(self):
        score = ClipScore(
            hook_strength=0.9,
            standalone_clarity=0.85,
            insight_value=0.88,
            virality_potential=0.7,
            audience_fit=0.92,
            overall=0.85,
        )
        assert score.overall == 0.85

    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            ClipScore(
                hook_strength=1.5,  # Too high
                standalone_clarity=0.5,
                insight_value=0.5,
                virality_potential=0.5,
                audience_fit=0.5,
                overall=0.5,
            )

    def test_negative_score(self):
        with pytest.raises(ValidationError):
            ClipScore(
                hook_strength=-0.1,
                standalone_clarity=0.5,
                insight_value=0.5,
                virality_potential=0.5,
                audience_fit=0.5,
                overall=0.5,
            )


class TestEditPlan:
    def test_valid_plan(self):
        plan = EditPlan(
            clip_id="clip_001",
            source_video_id="video_123",
            start_time=120.5,
            end_time=176.2,
            score=ClipScore(
                hook_strength=0.91,
                standalone_clarity=0.86,
                insight_value=0.89,
                virality_potential=0.77,
                audience_fit=0.92,
                overall=0.87,
            ),
        )
        assert plan.duration == pytest.approx(55.7, abs=0.1)
        assert plan.format == VideoFormat.VERTICAL_9_16

    def test_negative_start_time(self):
        with pytest.raises(ValidationError):
            EditPlan(
                clip_id="clip_001",
                source_video_id="video_123",
                start_time=-1.0,
                end_time=30.0,
                score=ClipScore(
                    hook_strength=0.5, standalone_clarity=0.5,
                    insight_value=0.5, virality_potential=0.5,
                    audience_fit=0.5, overall=0.5,
                ),
            )

    def test_start_equals_end_produces_zero_duration(self):
        """start_time == end_time is schema-valid but produces zero duration."""
        plan = EditPlan(
            clip_id="clip_002",
            source_video_id="video_123",
            start_time=50.0,
            end_time=50.0,
            score=ClipScore(
                hook_strength=0.5, standalone_clarity=0.5,
                insight_value=0.5, virality_potential=0.5,
                audience_fit=0.5, overall=0.5,
            ),
        )
        assert plan.duration == 0.0

    def test_duration_property(self):
        plan = EditPlan(
            clip_id="clip_003",
            source_video_id="video_123",
            start_time=10.0,
            end_time=70.0,
            score=ClipScore(
                hook_strength=0.5, standalone_clarity=0.5,
                insight_value=0.5, virality_potential=0.5,
                audience_fit=0.5, overall=0.5,
            ),
        )
        assert plan.duration == pytest.approx(60.0)

    def test_full_plan_json(self):
        plan = EditPlan(
            clip_id="clip_001",
            source_video_id="video_123",
            start_time=120.5,
            end_time=176.2,
            format=VideoFormat.VERTICAL_9_16,
            target_platform=TargetPlatform.YOUTUBE_SHORTS,
            hook="Most companies are not failing because of AI tools...",
            selection_reason="Strong standalone insight.",
            score=ClipScore(
                hook_strength=0.91, standalone_clarity=0.86,
                insight_value=0.89, virality_potential=0.77,
                audience_fit=0.92, overall=0.87,
            ),
            caption_style=CaptionStyle(type=CaptionType.KARAOKE),
            visual_edits=[
                VisualEdit(type=VisualEditType.ZOOM, timestamp=132.0, duration=1.2),
            ],
            audio=AudioSettings(normalize=True, noise_reduction=True),
            metadata=PublishMetadata(
                title="Why AI Tools Alone Do Not Transform Companies",
                description="A short insight.",
                hashtags=["AI", "BusinessTransformation"],
            ),
        )

        data = plan.model_dump()
        assert data["clip_id"] == "clip_001"
        assert len(data["visual_edits"]) == 1
        assert data["metadata"]["hashtags"] == ["AI", "BusinessTransformation"]

        # Round-trip
        restored = EditPlan.model_validate(data)
        assert restored.clip_id == plan.clip_id


class TestTranscriptSegment:
    def test_duration(self):
        seg = TranscriptSegment(start_time=10.0, end_time=40.0, text="Hello")
        assert seg.duration == 30.0

    def test_with_words(self):
        seg = TranscriptSegment(
            start_time=0.0,
            end_time=5.0,
            text="Hello world",
            words=[
                WordTimestamp(word="Hello", start=0.0, end=1.0),
                WordTimestamp(word="world", start=1.2, end=2.0),
            ],
        )
        assert len(seg.words) == 2


class TestTranscript:
    def test_word_count(self):
        t = Transcript(video_id="v1", full_text="one two three four five")
        assert t.word_count == 5


class TestVideoUploadParams:
    def test_defaults(self):
        params = VideoUploadParams()
        assert params.desired_clip_count == 5
        assert params.clip_duration_min == 30

    def test_clip_count_bounds(self):
        with pytest.raises(ValidationError):
            VideoUploadParams(desired_clip_count=0)

        with pytest.raises(ValidationError):
            VideoUploadParams(desired_clip_count=25)


class TestEnums:
    def test_job_statuses(self):
        assert JobStatus.PENDING == "pending"
        assert JobStatus.READY_FOR_REVIEW == "ready_for_review"

    def test_approval_status(self):
        assert ClipApprovalStatus.APPROVED == "approved"
