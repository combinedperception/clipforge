"""LangGraph agent pipeline for video editing decisions.

The graph flows:
  clean_transcript → segment → select_clips → edit_plans → metadata → qa_check
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    clean_transcript,
    create_edit_plans_node,
    generate_metadata_node,
    qa_check_node,
    score_candidates_node,
    segment_transcript_node,
    select_clips_node,
)
from app.agents.state import PipelineState
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_pipeline_graph() -> StateGraph:
    """Construct the LangGraph StateGraph for the video editing pipeline.

    Returns a compiled graph that can be invoked with a PipelineState dict.
    """
    graph = StateGraph(PipelineState)

    # Add nodes
    graph.add_node("clean_transcript", clean_transcript)
    graph.add_node("segment", segment_transcript_node)
    graph.add_node("score_candidates", score_candidates_node)
    graph.add_node("select_clips", select_clips_node)
    graph.add_node("edit_plans", create_edit_plans_node)
    graph.add_node("metadata", generate_metadata_node)
    graph.add_node("qa_check", qa_check_node)

    # Define edges (linear pipeline for MVP)
    graph.add_edge(START, "clean_transcript")
    graph.add_edge("clean_transcript", "segment")
    graph.add_edge("segment", "score_candidates")
    graph.add_edge("score_candidates", "select_clips")
    graph.add_edge("select_clips", "edit_plans")
    graph.add_edge("edit_plans", "metadata")
    graph.add_edge("metadata", "qa_check")
    graph.add_edge("qa_check", END)

    return graph


# Pre-built compiled graph instance
pipeline_graph = build_pipeline_graph().compile()


def run_pipeline(
    video_id: str,
    transcript: object,
    target_clip_count: int = 5,
    clip_duration_min: float = 30.0,
    clip_duration_max: float = 90.0,
    target_audience: str = "",
    tone: str = "professional",
) -> PipelineState:
    """Run the full agent pipeline synchronously.

    Args:
        video_id: Source video identifier.
        transcript: Transcript object from transcription step.
        target_clip_count: How many clips to produce.
        clip_duration_min: Minimum clip duration in seconds.
        clip_duration_max: Maximum clip duration in seconds.
        target_audience: Description of target audience.
        tone: Desired tone for the content.

    Returns:
        Final pipeline state with edit_plans, metadata, and qa_results.
    """
    logger.info(
        "pipeline_start",
        video_id=video_id,
        target_clips=target_clip_count,
    )

    initial_state: PipelineState = {
        "video_id": video_id,
        "transcript_raw": transcript,
        "target_clip_count": target_clip_count,
        "clip_duration_min": clip_duration_min,
        "clip_duration_max": clip_duration_max,
        "target_audience": target_audience,
        "tone": tone,
        "errors": [],
    }

    result = pipeline_graph.invoke(initial_state)

    errors = result.get("errors", [])
    plan_count = len(result.get("edit_plans", []))

    if errors:
        logger.warning("pipeline_completed_with_errors", video_id=video_id, errors=errors)
    else:
        logger.info("pipeline_complete", video_id=video_id, edit_plans=plan_count)

    return result
