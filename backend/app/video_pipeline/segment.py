"""Transcript segmentation into candidate clip moments."""

from __future__ import annotations

from app.schemas.transcript import Transcript, TranscriptSegment


def segment_transcript(
    transcript: Transcript,
    min_duration: float = 30.0,
    max_duration: float = 90.0,
) -> list[TranscriptSegment]:
    """Group transcript segments into candidate moments of appropriate duration.

    This is a deterministic fallback. The agentic workflow may override
    this with LLM-based intelligent segmentation.

    Args:
        transcript: Full transcript.
        min_duration: Minimum candidate duration in seconds.
        max_duration: Maximum candidate duration in seconds.

    Returns:
        List of merged TranscriptSegment objects representing candidates.
    """
    if not transcript.segments:
        return []

    candidates: list[TranscriptSegment] = []
    buffer: list[TranscriptSegment] = []
    buffer_start = transcript.segments[0].start_time
    last_seg_index = len(transcript.segments) - 1

    for i, seg in enumerate(transcript.segments):
        buffer.append(seg)
        buffer_duration = seg.end_time - buffer_start

        if buffer_duration >= min_duration:
            # Merge buffered segments into one candidate
            merged = _merge_segments(buffer, len(candidates))
            candidates.append(merged)

            # Reset buffer
            buffer = []
            if i < last_seg_index:
                buffer_start = seg.end_time

    # Handle leftover segments
    if buffer:
        total_duration = buffer[-1].end_time - buffer[0].start_time
        if total_duration >= min_duration * 0.5:  # Accept if at least half min duration
            merged = _merge_segments(buffer, len(candidates))
            candidates.append(merged)

    return candidates


def _merge_segments(segments: list[TranscriptSegment], index: int) -> TranscriptSegment:
    """Merge multiple transcript segments into a single candidate segment."""
    return TranscriptSegment(
        id=f"candidate_{index:03d}",
        start_time=segments[0].start_time,
        end_time=segments[-1].end_time,
        text=" ".join(s.text for s in segments),
        speaker=segments[0].speaker,
    )
