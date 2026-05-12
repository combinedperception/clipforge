"""Tests for agent workflow nodes and graph."""

from __future__ import annotations

import pytest

from app.agents.nodes import (
    clean_transcript,
    create_edit_plans_node,
    generate_metadata_node,
    qa_check_node,
    score_candidates_node,
    segment_transcript_node,
    select_clips_node,
)
from app.schemas.clip import ClipScore, EditPlan, PublishMetadata
from app.schemas.transcript import Transcript, TranscriptSegment


# ── Helpers ──────────────────────────────────────────────


def _make_transcript(n_segments: int = 10, seg_duration: float = 10.0) -> Transcript:
    """Build a Transcript with *n_segments* consecutive segments."""
    segments = [
        TranscriptSegment(
            id=f"s{i}",
            start_time=i * seg_duration,
            end_time=(i + 1) * seg_duration,
            text=f"This is segment number {i} with some meaningful content about AI transformation.",
        )
        for i in range(n_segments)
    ]
    return Transcript(
        video_id="v_test",
        segments=segments,
        full_text=" ".join(s.text for s in segments),
        duration_seconds=n_segments * seg_duration,
    )


def _default_score() -> ClipScore:
    return ClipScore(
        hook_strength=0.8,
        standalone_clarity=0.7,
        insight_value=0.9,
        virality_potential=0.6,
        audience_fit=0.75,
        overall=0.8,
    )


# ═══════════════════════════════════════════════════════════
# Node tests
# ═══════════════════════════════════════════════════════════


class TestCleanTranscript:
    def test_passthrough(self):
        transcript = _make_transcript()
        state = {"video_id": "v1", "transcript_raw": transcript}
        result = clean_transcript(state)

        assert result["transcript_clean"] is transcript
        assert result["current_stage"] == "clean_transcript"

    def test_missing_transcript_produces_error(self):
        result = clean_transcript({"video_id": "v1", "errors": []})
        assert len(result["errors"]) == 1
        assert "No raw transcript" in result["errors"][0]


class TestSegmentTranscriptNode:
    def test_produces_candidates(self):
        transcript = _make_transcript(n_segments=10, seg_duration=10.0)
        state = {
            "video_id": "v1",
            "transcript_clean": transcript,
            "clip_duration_min": 30.0,
            "clip_duration_max": 90.0,
        }
        result = segment_transcript_node(state)

        assert result["current_stage"] == "segment"
        assert len(result["candidates"]) > 0

    def test_missing_transcript(self):
        result = segment_transcript_node({"video_id": "v1", "errors": []})
        assert "No cleaned transcript" in result["errors"][0]


class TestScoreCandidatesNode:
    def test_scores_all_candidates(self):
        candidates = [
            TranscriptSegment(start_time=0, end_time=45, text="Great insight about AI."),
            TranscriptSegment(start_time=50, end_time=95, text="Another key moment."),
        ]
        state = {"video_id": "v1", "candidates": candidates, "errors": []}
        result = score_candidates_node(state)

        assert result["current_stage"] == "score"
        assert len(result["candidate_scores"]) == 2
        for score in result["candidate_scores"]:
            assert 0 <= score.overall <= 1

    def test_no_candidates_produces_error(self):
        result = score_candidates_node({"video_id": "v1", "candidates": [], "errors": []})
        assert "No candidates to score" in result["errors"][0]


class TestSelectClipsNode:
    def test_selects_top_n(self):
        candidates = [
            TranscriptSegment(start_time=i * 30, end_time=(i + 1) * 30, text=f"Segment {i}")
            for i in range(6)
        ]
        from app.video_pipeline.clip_selection import score_segment_heuristic

        scores = [score_segment_heuristic(c) for c in candidates]
        state = {
            "video_id": "v1",
            "candidates": candidates,
            "candidate_scores": scores,
            "target_clip_count": 3,
            "errors": [],
        }
        result = select_clips_node(state)

        assert result["current_stage"] == "select"
        assert len(result["candidates"]) <= 3

    def test_empty_candidates(self):
        result = select_clips_node({"video_id": "v1", "candidates": [], "errors": []})
        assert "No candidates to select from" in result["errors"][0]


class TestCreateEditPlansNode:
    def test_creates_plans_for_candidates(self):
        candidates = [
            TranscriptSegment(start_time=10, end_time=55, text="Important AI insight."),
            TranscriptSegment(start_time=60, end_time=110, text="Second key moment."),
        ]
        state = {"video_id": "v_test", "candidates": candidates, "errors": []}
        result = create_edit_plans_node(state)

        assert result["current_stage"] == "edit_plans"
        plans = result["edit_plans"]
        assert len(plans) == 2

        for plan in plans:
            assert isinstance(plan, EditPlan)
            assert plan.source_video_id == "v_test"
            assert plan.start_time >= 0
            assert plan.end_time > plan.start_time
            assert 0 <= plan.score.overall <= 1
            assert plan.clip_id.startswith("clip_")

    def test_empty_candidates(self):
        result = create_edit_plans_node({"video_id": "v1", "candidates": [], "errors": []})
        assert "No candidates for edit plans" in result["errors"][0]


class TestGenerateMetadataNode:
    def test_populates_metadata(self):
        candidates = [
            TranscriptSegment(start_time=10, end_time=55, text="AI transformation insight."),
        ]
        plan = EditPlan(
            clip_id="clip_m1",
            source_video_id="v1",
            start_time=10,
            end_time=55,
            hook="AI transformation insight.",
            score=_default_score(),
        )
        state = {
            "video_id": "v1",
            "edit_plans": [plan],
            "candidates": candidates,
            "errors": [],
        }
        result = generate_metadata_node(state)

        assert result["current_stage"] == "metadata"
        updated_plans = result["edit_plans"]
        assert len(updated_plans) == 1
        assert updated_plans[0].metadata.title != ""

    def test_no_plans(self):
        result = generate_metadata_node({"video_id": "v1", "edit_plans": [], "errors": []})
        assert "No edit plans for metadata" in result["errors"][0]


class TestQACheckNode:
    def test_valid_plans_pass(self):
        plan = EditPlan(
            clip_id="clip_qa1",
            source_video_id="v1",
            start_time=10,
            end_time=55,
            hook="Great hook",
            score=_default_score(),
            metadata=PublishMetadata(title="A Title", description="Desc"),
        )
        result = qa_check_node({"video_id": "v1", "edit_plans": [plan], "errors": []})

        assert result["current_stage"] == "qa"
        assert result["qa_results"][0]["passed"] is True
        assert result["qa_results"][0]["issues"] == []

    def test_clip_too_short_flagged(self):
        plan = EditPlan(
            clip_id="clip_short",
            source_video_id="v1",
            start_time=10,
            end_time=12,  # 2s — below 5s minimum
            hook="Hook",
            score=_default_score(),
            metadata=PublishMetadata(title="T"),
        )
        result = qa_check_node({"video_id": "v1", "edit_plans": [plan], "errors": []})
        issues = result["qa_results"][0]["issues"]
        assert any("too short" in i for i in issues)
        assert result["qa_results"][0]["passed"] is False

    def test_clip_too_long_flagged(self):
        plan = EditPlan(
            clip_id="clip_long",
            source_video_id="v1",
            start_time=0,
            end_time=200,  # 200s — above 180s limit
            hook="Hook",
            score=_default_score(),
            metadata=PublishMetadata(title="T"),
        )
        result = qa_check_node({"video_id": "v1", "edit_plans": [plan], "errors": []})
        issues = result["qa_results"][0]["issues"]
        assert any("too long" in i for i in issues)

    def test_missing_hook_flagged(self):
        plan = EditPlan(
            clip_id="clip_nh",
            source_video_id="v1",
            start_time=10,
            end_time=55,
            hook="",
            score=_default_score(),
            metadata=PublishMetadata(title="T"),
        )
        result = qa_check_node({"video_id": "v1", "edit_plans": [plan], "errors": []})
        issues = result["qa_results"][0]["issues"]
        assert any("Missing hook" in i for i in issues)

    def test_missing_title_flagged(self):
        plan = EditPlan(
            clip_id="clip_nt",
            source_video_id="v1",
            start_time=10,
            end_time=55,
            hook="Hook",
            score=_default_score(),
            metadata=PublishMetadata(title=""),
        )
        result = qa_check_node({"video_id": "v1", "edit_plans": [plan], "errors": []})
        issues = result["qa_results"][0]["issues"]
        assert any("Missing title" in i for i in issues)
