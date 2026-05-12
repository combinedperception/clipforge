"""Transcript and segment schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WordTimestamp(BaseModel):
    """Single word with precise timing."""

    word: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    confidence: float = Field(default=1.0, ge=0, le=1)


class TranscriptSegment(BaseModel):
    """A chunk of transcript with start/end time."""

    id: str = ""
    start_time: float = Field(ge=0)
    end_time: float = Field(ge=0)
    text: str
    speaker: str = ""
    words: list[WordTimestamp] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class Transcript(BaseModel):
    """Full transcript of a video."""

    video_id: str
    language: str = "en"
    segments: list[TranscriptSegment] = Field(default_factory=list)
    full_text: str = ""
    duration_seconds: float = 0

    @property
    def word_count(self) -> int:
        return len(self.full_text.split())
