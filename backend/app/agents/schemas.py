"""Pydantic schemas for structured LLM output parsing."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CleanedSegmentOutput(BaseModel):
    id: str
    start_time: float
    end_time: float
    text: str
    speaker: str = ""


class SegmentCandidateOutput(BaseModel):
    start_time: float
    end_time: float
    text: str
    reason: str = ""


class ClipScoreOutput(BaseModel):
    hook_strength: float = Field(ge=0, le=1)
    standalone_clarity: float = Field(ge=0, le=1)
    insight_value: float = Field(ge=0, le=1)
    virality_potential: float = Field(ge=0, le=1)
    audience_fit: float = Field(ge=0, le=1)
    overall: float = Field(ge=0, le=1)


class SelectedClipOutput(BaseModel):
    start_time: float
    end_time: float
    text: str
    hook: str = ""
    selection_reason: str = ""
    score: ClipScoreOutput


class MetadataOutput(BaseModel):
    clip_id: str
    title: str
    description: str
    hashtags: list[str] = Field(default_factory=list)


class CleanedTranscriptResponse(BaseModel):
    segments: list[CleanedSegmentOutput]


class SegmentationResponse(BaseModel):
    candidates: list[SegmentCandidateOutput]


class ClipSelectionResponse(BaseModel):
    selected: list[SelectedClipOutput]


class MetadataResponse(BaseModel):
    metadata: list[MetadataOutput]
