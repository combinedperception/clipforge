"""Agent node functions for the video editing pipeline.

Each node is a pure function: PipelineState → partial PipelineState update.
Nodes that need LLM access accept it via the state (injected at graph build time).
"""

from __future__ import annotations

import json
import uuid

from app.agents.prompts import (
    CLIP_SELECTION_PROMPT,
    EDIT_PLAN_PROMPT,
    METADATA_PROMPT,
    SEGMENTATION_PROMPT,
    TRANSCRIPT_CLEANING_PROMPT,
)
from app.agents.state import PipelineState
from app.core.logging import get_logger
from app.schemas.clip import (
    AudioSettings,
    CaptionStyle,
    ClipScore,
    EditPlan,
    PublishMetadata,
)
from app.schemas.enums import TargetPlatform, VideoFormat
from app.schemas.transcript import Transcript, TranscriptSegment
from app.video_pipeline.clip_selection import score_segment_heuristic, select_top_clips
from app.video_pipeline.metadata import generate_metadata_heuristic
from app.video_pipeline.segment import segment_transcript

logger = get_logger(__name__)


# ── Node: Clean Transcript ────────────────────────────────


def clean_transcript(state: PipelineState) -> dict:
    """Clean the raw transcript – remove filler, fix errors.

    MVP: Pass-through (no LLM call). LLM-based cleaning can be
    enabled when OPENAI_API_KEY is configured.
    """
    logger.info("node_clean_transcript", video_id=state.get("video_id", ""))

    raw = state.get("transcript_raw")
    if raw is None:
        return {"errors": state.get("errors", []) + ["No raw transcript provided"], "current_stage": "clean_transcript"}

    # MVP: pass through unchanged
    return {
        "transcript_clean": raw,
        "current_stage": "clean_transcript",
    }


# ── Node: Segment Transcript ─────────────────────────────


def segment_transcript_node(state: PipelineState) -> dict:
    """Segment the cleaned transcript into candidate moments."""
    logger.info("node_segment_transcript", video_id=state.get("video_id", ""))

    transcript = state.get("transcript_clean")
    if transcript is None:
        return {"errors": state.get("errors", []) + ["No cleaned transcript"], "current_stage": "segment"}

    min_dur = state.get("clip_duration_min", 30.0)
    max_dur = state.get("clip_duration_max", 90.0)

    candidates = segment_transcript(transcript, min_duration=min_dur, max_duration=max_dur)

    logger.info("segmentation_complete", candidate_count=len(candidates))
    return {
        "segments": candidates,
        "candidates": candidates,
        "current_stage": "segment",
    }


# ── Node: Score Candidates ────────────────────────────────


def score_candidates_node(state: PipelineState) -> dict:
    """Score each candidate segment using heuristic scoring."""
    logger.info("node_score_candidates", video_id=state.get("video_id", ""))

    candidates = state.get("candidates", [])
    if not candidates:
        return {"errors": state.get("errors", []) + ["No candidates to score"], "current_stage": "score"}

    scores = [score_segment_heuristic(c) for c in candidates]

    logger.info("scoring_complete", candidate_count=len(scores))
    return {
        "candidate_scores": scores,
        "current_stage": "score",
    }


# ── Node: Select Clips ───────────────────────────────────


def select_clips_node(state: PipelineState) -> dict:
    """Select the top-N candidate clips from scored candidates."""
    logger.info("node_select_clips", video_id=state.get("video_id", ""))

    candidates = state.get("candidates", [])
    scores = state.get("candidate_scores", [])

    if not candidates:
        return {"errors": state.get("errors", []) + ["No candidates to select from"], "current_stage": "select"}

    top_n = state.get("target_clip_count", 5)

    # If scores weren't produced by a prior node, compute them now
    if not scores:
        scores = [score_segment_heuristic(c) for c in candidates]

    selected = select_top_clips(candidates, scores, top_n=top_n)
    selected_segments = [seg for seg, _ in selected]

    logger.info("selection_complete", selected_count=len(selected_segments))
    return {
        "candidates": selected_segments,
        "current_stage": "select",
    }


# ── Node: Create Edit Plans ──────────────────────────────


def create_edit_plans_node(state: PipelineState) -> dict:
    """Create structured edit plans for selected clips."""
    logger.info("node_create_edit_plans", video_id=state.get("video_id", ""))

    candidates = state.get("candidates", [])
    video_id = state.get("video_id", "unknown")

    if not candidates:
        return {"errors": state.get("errors", []) + ["No candidates for edit plans"], "current_stage": "edit_plans"}

    edit_plans: list[EditPlan] = []
    for i, seg in enumerate(candidates):
        score = score_segment_heuristic(seg)
        clip_id = f"clip_{uuid.uuid4().hex[:8]}"

        sentences = seg.text.split(". ")
        hook = sentences[0].strip() if sentences else seg.text[:100]

        plan = EditPlan(
            clip_id=clip_id,
            source_video_id=video_id,
            start_time=seg.start_time,
            end_time=seg.end_time,
            format=VideoFormat.VERTICAL_9_16,
            target_platform=TargetPlatform.YOUTUBE_SHORTS,
            hook=hook,
            selection_reason=f"Selected as candidate #{i + 1} by scoring pipeline.",
            score=score,
            caption_style=CaptionStyle(),
            visual_edits=[],
            audio=AudioSettings(normalize=True, noise_reduction=False),
            metadata=PublishMetadata(),
        )
        edit_plans.append(plan)

    logger.info("edit_plans_created", plan_count=len(edit_plans))
    return {
        "edit_plans": edit_plans,
        "current_stage": "edit_plans",
    }


# ── Node: Generate Metadata ──────────────────────────────


def generate_metadata_node(state: PipelineState) -> dict:
    """Generate titles, descriptions, and hashtags for each clip."""
    logger.info("node_generate_metadata", video_id=state.get("video_id", ""))

    edit_plans = state.get("edit_plans", [])
    candidates = state.get("candidates", [])

    if not edit_plans:
        return {"errors": state.get("errors", []) + ["No edit plans for metadata"], "current_stage": "metadata"}

    metadata_list: list[PublishMetadata] = []
    updated_plans: list[EditPlan] = []

    for i, plan in enumerate(edit_plans):
        # Find corresponding segment
        seg = candidates[i] if i < len(candidates) else TranscriptSegment(
            start_time=plan.start_time, end_time=plan.end_time, text=plan.hook
        )

        meta = generate_metadata_heuristic(seg, hook=plan.hook)
        metadata_list.append(meta)

        # Update the plan with metadata
        updated_plan = plan.model_copy(update={"metadata": meta})
        updated_plans.append(updated_plan)

    logger.info("metadata_generated", count=len(metadata_list))
    return {
        "edit_plans": updated_plans,
        "metadata_list": metadata_list,
        "current_stage": "metadata",
    }


# ── Node: QA Check ────────────────────────────────────────


def qa_check_node(state: PipelineState) -> dict:
    """Run deterministic quality checks on edit plans."""
    logger.info("node_qa_check", video_id=state.get("video_id", ""))

    edit_plans = state.get("edit_plans", [])
    qa_results: list[dict] = []

    for plan in edit_plans:
        issues: list[str] = []

        if plan.start_time >= plan.end_time:
            issues.append(f"Invalid timestamps: start >= end")
        if plan.duration < 5:
            issues.append(f"Clip too short: {plan.duration:.1f}s")
        if plan.duration > 180:
            issues.append(f"Clip too long: {plan.duration:.1f}s")
        if not plan.metadata.title:
            issues.append("Missing title")
        if not plan.hook:
            issues.append("Missing hook")

        qa_results.append({
            "clip_id": plan.clip_id,
            "passed": len(issues) == 0,
            "issues": issues,
        })

    failed_count = sum(1 for r in qa_results if not r["passed"])
    logger.info("qa_complete", total=len(qa_results), failed=failed_count)

    return {
        "qa_results": qa_results,
        "current_stage": "qa",
    }
