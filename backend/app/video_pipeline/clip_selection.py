"""Clip selection scoring – deterministic fallback + AI-driven scoring."""

from __future__ import annotations

from app.schemas.clip import ClipScore
from app.schemas.transcript import TranscriptSegment


def score_segment_heuristic(segment: TranscriptSegment) -> ClipScore:
    """Produce a basic heuristic score for a candidate segment.

    This is a deterministic fallback. The agentic workflow produces
    higher-quality scores via LLM evaluation.
    """
    text = segment.text.lower()
    word_count = len(text.split())
    duration = segment.duration

    # Simple heuristics
    has_question = "?" in text
    has_numbers = any(c.isdigit() for c in text)
    word_density = min(word_count / max(duration, 1) / 3.0, 1.0)  # ~3 words/sec is normal

    hook_strength = min(0.5 + (0.2 if has_question else 0) + (0.1 if has_numbers else 0), 1.0)
    standalone_clarity = min(word_density + 0.3, 1.0)
    insight_value = min(0.4 + (0.15 if has_numbers else 0) + (0.1 * min(word_count / 50, 1)), 1.0)
    virality_potential = min(0.3 + (0.2 if has_question else 0) + word_density * 0.3, 1.0)
    audience_fit = 0.7  # Default without context

    overall = (
        hook_strength * 0.25
        + standalone_clarity * 0.20
        + insight_value * 0.25
        + virality_potential * 0.15
        + audience_fit * 0.15
    )

    return ClipScore(
        hook_strength=round(hook_strength, 2),
        standalone_clarity=round(standalone_clarity, 2),
        insight_value=round(insight_value, 2),
        virality_potential=round(virality_potential, 2),
        audience_fit=round(audience_fit, 2),
        overall=round(overall, 2),
    )


def select_top_clips(
    candidates: list[TranscriptSegment],
    scores: list[ClipScore],
    top_n: int = 5,
) -> list[tuple[TranscriptSegment, ClipScore]]:
    """Select the top-N clips by overall score.

    Args:
        candidates: Candidate segments.
        scores: Corresponding scores.
        top_n: Number of clips to select.

    Returns:
        List of (segment, score) tuples, sorted by score descending.
    """
    paired = list(zip(candidates, scores))
    paired.sort(key=lambda x: x[1].overall, reverse=True)
    return paired[:top_n]
