"""Agent state definition for the video editing pipeline."""

from __future__ import annotations

from typing import TypedDict

from app.schemas.clip import ClipScore, EditPlan, PublishMetadata
from app.schemas.transcript import Transcript, TranscriptSegment


class PipelineState(TypedDict, total=False):
    """Shared state flowing through the LangGraph agent pipeline.

    Each agent node reads from and writes to this state.
    """

    # ── Inputs ────────────────────────────────────────────
    video_id: str
    transcript_raw: Transcript
    target_clip_count: int
    clip_duration_min: float
    clip_duration_max: float
    target_audience: str
    tone: str

    # ── Intermediate ──────────────────────────────────────
    transcript_clean: Transcript
    segments: list[TranscriptSegment]
    candidates: list[TranscriptSegment]
    candidate_scores: list[ClipScore]

    # ── Outputs ───────────────────────────────────────────
    edit_plans: list[EditPlan]
    metadata_list: list[PublishMetadata]
    qa_results: list[dict]

    # ── Control ───────────────────────────────────────────
    errors: list[str]
    current_stage: str
