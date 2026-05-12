"""Tests for video pipeline functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.clip import ClipScore, EditPlan
from app.schemas.transcript import Transcript, TranscriptSegment
from app.video_pipeline.captions import format_srt_time, generate_srt
from app.video_pipeline.clip_selection import score_segment_heuristic, select_top_clips
from app.video_pipeline.ingest import validate_video_file
from app.video_pipeline.metadata import generate_metadata_heuristic
from app.video_pipeline.segment import segment_transcript


def _default_score() -> ClipScore:
    return ClipScore(
        hook_strength=0.8,
        standalone_clarity=0.7,
        insight_value=0.9,
        virality_potential=0.6,
        audience_fit=0.75,
        overall=0.8,
    )


class TestValidateVideo:
    def test_valid_mp4(self):
        # Should not raise
        validate_video_file("test.mp4", "video/mp4", 1024, 500 * 1024 * 1024)

    def test_invalid_extension(self):
        from app.core.errors import InvalidVideoError
        with pytest.raises(InvalidVideoError, match="Unsupported file extension"):
            validate_video_file("test.txt", "text/plain", 1024, 500 * 1024 * 1024)

    def test_too_large(self):
        from app.core.errors import InvalidVideoError
        with pytest.raises(InvalidVideoError, match="exceeds limit"):
            validate_video_file("test.mp4", "video/mp4", 1024 * 1024 * 600, 500 * 1024 * 1024)

    def test_empty_file(self):
        from app.core.errors import InvalidVideoError
        with pytest.raises(InvalidVideoError, match="empty"):
            validate_video_file("test.mp4", "video/mp4", 0, 500 * 1024 * 1024)


class TestFormatSRTTime:
    def test_zero(self):
        assert format_srt_time(0) == "00:00:00,000"

    def test_simple(self):
        assert format_srt_time(65.5) == "00:01:05,500"

    def test_hours(self):
        assert format_srt_time(3661.123) == "01:01:01,123"


class TestGenerateSRT:
    def test_basic_srt(self, tmp_path):
        segments = [
            TranscriptSegment(start_time=0.0, end_time=5.0, text="Hello world"),
            TranscriptSegment(start_time=5.0, end_time=10.0, text="Second segment"),
        ]
        output = tmp_path / "test.srt"
        result = generate_srt(segments, output)

        assert result.exists()
        content = result.read_text()
        assert "Hello world" in content
        assert "Second segment" in content
        assert "00:00:00,000 --> 00:00:05,000" in content

    def test_srt_with_offset(self, tmp_path):
        segments = [
            TranscriptSegment(start_time=120.0, end_time=125.0, text="Clip text"),
        ]
        output = tmp_path / "test.srt"
        result = generate_srt(segments, output, offset=120.0)

        content = result.read_text()
        assert "00:00:00,000 --> 00:00:05,000" in content


class TestSegmentTranscript:
    def test_basic_segmentation(self):
        segments = [
            TranscriptSegment(id=f"s{i}", start_time=i * 10.0, end_time=(i + 1) * 10.0, text=f"Segment {i}")
            for i in range(10)
        ]
        transcript = Transcript(video_id="v1", segments=segments, duration_seconds=100)

        candidates = segment_transcript(transcript, min_duration=30, max_duration=90)
        assert len(candidates) > 0
        for c in candidates:
            assert c.duration >= 15  # At least half of min_duration

    def test_empty_transcript(self):
        transcript = Transcript(video_id="v1", segments=[])
        candidates = segment_transcript(transcript)
        assert candidates == []

    def test_duplicate_content_segments_no_double_merge(self):
        """Segments with identical text should not trigger model-equality bugs."""
        segments = [
            TranscriptSegment(id=f"s{i}", start_time=i * 10.0, end_time=(i + 1) * 10.0, text="Same text")
            for i in range(6)
        ]
        transcript = Transcript(video_id="v1", segments=segments, duration_seconds=60)
        candidates = segment_transcript(transcript, min_duration=30, max_duration=90)
        # Should produce candidates without duplicating the last segment
        total_end = max(c.end_time for c in candidates)
        assert total_end <= 60.0


class TestClipScoring:
    def test_heuristic_scoring(self):
        seg = TranscriptSegment(
            start_time=0, end_time=45,
            text="What if I told you that 90% of companies fail at AI transformation?"
        )
        score = score_segment_heuristic(seg)
        assert 0 <= score.overall <= 1
        assert score.hook_strength > 0.5  # Has a question

    def test_select_top_clips(self):
        segs = [
            TranscriptSegment(start_time=i * 30, end_time=(i + 1) * 30, text=f"Seg {i}")
            for i in range(5)
        ]
        scores = [score_segment_heuristic(s) for s in segs]
        top = select_top_clips(segs, scores, top_n=3)
        assert len(top) == 3


class TestMetadataGeneration:
    def test_basic_metadata(self):
        seg = TranscriptSegment(
            start_time=0, end_time=45,
            text="AI transformation requires cultural change. Companies must adapt their Operating Model."
        )
        meta = generate_metadata_heuristic(seg)
        assert meta.title
        assert meta.description

    def test_frequency_based_hashtags(self):
        """Hashtags should be extracted by word frequency, not CamelCase."""
        seg = TranscriptSegment(
            start_time=0, end_time=30,
            text=(
                "machine learning drives innovation in machine learning. "
                "Data science and data engineering work together for data pipelines."
            ),
        )
        meta = generate_metadata_heuristic(seg)
        # 'data' and 'machine' should appear — they're frequent 4+ char words
        hashtags_lower = [h.lower() for h in meta.hashtags]
        assert "data" in hashtags_lower
        assert "machine" in hashtags_lower
        # Stopwords and short words should not appear
        for tag in meta.hashtags:
            assert tag.lower() not in {"and", "in", "for", "the"}
            assert len(tag) >= 4


class TestQAStreamCheck:
    """Tests for the ffprobe audio/video stream check in run_qa_checks."""

    def test_qa_fails_when_audio_missing(self, tmp_path):
        from unittest.mock import patch
        import subprocess

        from app.video_pipeline.qa import run_qa_checks

        rendered = tmp_path / "clip.mp4"
        rendered.write_bytes(b"\x00" * 100)

        plan = EditPlan(
            clip_id="qa_test",
            source_video_id="vid_qa",
            start_time=0, end_time=30,
            score=_default_score(),
        )

        # ffprobe returns only a video stream
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='{"streams":[{"codec_type":"video"}]}', stderr="",
            )
            result = run_qa_checks(plan, rendered)
            assert not result.passed
            assert any("audio" in issue.lower() for issue in result.issues)

    def test_qa_passes_with_both_streams(self, tmp_path):
        from unittest.mock import patch
        import subprocess

        from app.video_pipeline.qa import run_qa_checks

        rendered = tmp_path / "clip.mp4"
        rendered.write_bytes(b"\x00" * 100)

        plan = EditPlan(
            clip_id="qa_test",
            source_video_id="vid_qa",
            start_time=0, end_time=30,
            score=_default_score(),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='{"streams":[{"codec_type":"video"},{"codec_type":"audio"}]}', stderr="",
            )
            result = run_qa_checks(plan, rendered)
            assert result.passed
