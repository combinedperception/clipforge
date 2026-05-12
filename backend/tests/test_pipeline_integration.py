"""Tests for pipeline integration, video loading, and FFmpeg probing."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.video_pipeline.audio import check_ffmpeg_available, run_ffmpeg
from app.video_pipeline.ingest import ALLOWED_EXTENSIONS, validate_video_file

# ── Locate the test video ──────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
_TEST_FILES_DIR = _ROOT / "test_files"


def _find_test_video() -> Path | None:
    """Return the first .mp4 in test_files/, or None."""
    if not _TEST_FILES_DIR.is_dir():
        return None
    for f in _TEST_FILES_DIR.iterdir():
        if f.suffix.lower() in ALLOWED_EXTENSIONS:
            return f
    return None


TEST_VIDEO = _find_test_video()
_skip_no_video = pytest.mark.skipif(TEST_VIDEO is None, reason="No test video in test_files/")
_skip_no_ffmpeg = pytest.mark.skipif(not check_ffmpeg_available(), reason="FFmpeg not installed")


# ── Test: video loading from test_files/ ────────────────────────────────


class TestLocalVideoLoading:
    """Test that test_files/ contains a usable video."""

    @_skip_no_video
    def test_test_video_exists(self):
        assert TEST_VIDEO.is_file()
        assert TEST_VIDEO.stat().st_size > 0

    @_skip_no_video
    def test_validate_test_video(self):
        validate_video_file(
            filename=TEST_VIDEO.name,
            content_type=None,
            size_bytes=TEST_VIDEO.stat().st_size,
            max_size_bytes=500 * 1024 * 1024,
        )

    def test_validate_missing_video(self):
        with pytest.raises(Exception):
            validate_video_file(
                filename="nonexistent.txt",
                content_type=None,
                size_bytes=100,
                max_size_bytes=500 * 1024 * 1024,
            )

    def test_validate_invalid_extension(self):
        with pytest.raises(Exception, match="Unsupported file extension"):
            validate_video_file(
                filename="video.exe",
                content_type=None,
                size_bytes=100,
                max_size_bytes=500 * 1024 * 1024,
            )

    def test_validate_octet_stream_accepted(self):
        """application/octet-stream should be accepted for valid extensions."""
        validate_video_file(
            filename="test.mp4",
            content_type="application/octet-stream",
            size_bytes=100,
            max_size_bytes=500 * 1024 * 1024,
        )

    def test_validate_wrong_mime_rejected(self):
        """Non-video, non-octet-stream MIME types should be rejected."""
        with pytest.raises(Exception, match="Unsupported MIME type"):
            validate_video_file(
                filename="test.mp4",
                content_type="text/html",
                size_bytes=100,
                max_size_bytes=500 * 1024 * 1024,
            )

    def test_validate_empty_file(self):
        with pytest.raises(Exception, match="empty"):
            validate_video_file(
                filename="test.mp4",
                content_type="video/mp4",
                size_bytes=0,
                max_size_bytes=500 * 1024 * 1024,
            )


# ── Test: FFmpeg probing/conversion ─────────────────────────────────────


class TestFFmpegProbing:
    """Test FFmpeg availability and probing capabilities."""

    @_skip_no_ffmpeg
    def test_ffmpeg_available(self):
        assert check_ffmpeg_available()

    @_skip_no_ffmpeg
    @_skip_no_video
    def test_ffprobe_test_video(self):
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size:stream=codec_type",
             "-of", "json", str(TEST_VIDEO)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert "format" in data
        assert float(data["format"]["duration"]) > 0
        streams = data.get("streams", [])
        assert any(s["codec_type"] == "video" for s in streams)

    @_skip_no_ffmpeg
    @_skip_no_video
    def test_extract_audio(self, tmp_path):
        from app.video_pipeline.audio import extract_audio

        audio_out = tmp_path / "test_audio.wav"
        extract_audio(TEST_VIDEO, audio_out)
        assert audio_out.exists()
        assert audio_out.stat().st_size > 0

    @_skip_no_ffmpeg
    def test_ffmpeg_error_on_missing_input(self):
        from app.core.errors import FFmpegError

        with pytest.raises(FileNotFoundError):
            from app.video_pipeline.audio import extract_audio
            extract_audio(Path("/nonexistent/video.mp4"), Path("/tmp/out.wav"))


# ── Test: Pipeline execution with mock transcription ────────────────────


class TestPipelineExecution:
    """Test the agent pipeline with mock transcription data."""

    def test_mock_transcription_service(self):
        import asyncio
        from app.video_pipeline.transcribe import MockTranscriptionService

        service = MockTranscriptionService()
        transcript = asyncio.run(service.transcribe(Path("/fake/audio.wav")))
        assert len(transcript.segments) == 3
        assert transcript.duration_seconds == 90.0
        assert transcript.word_count > 0

    def test_agent_pipeline_with_mock_transcript(self):
        import asyncio
        from app.agents.graph import run_pipeline
        from app.video_pipeline.transcribe import MockTranscriptionService

        service = MockTranscriptionService()
        transcript = asyncio.run(service.transcribe(Path("/fake/audio.wav")))
        transcript.video_id = "test_pipeline"

        result = run_pipeline(
            video_id="test_pipeline",
            transcript=transcript,
            target_clip_count=3,
        )

        assert "edit_plans" in result
        assert len(result["edit_plans"]) > 0
        assert "qa_results" in result
        # All plans should have required fields
        for plan in result["edit_plans"]:
            assert plan.clip_id
            assert plan.start_time >= 0
            assert plan.end_time > plan.start_time
            assert plan.hook
            assert plan.metadata.title

    def test_pipeline_errors_field(self):
        from app.agents.graph import run_pipeline
        from app.schemas.transcript import Transcript

        # Empty transcript should still run without crashing
        empty = Transcript(
            video_id="test",
            language="en",
            segments=[],
            full_text="",
            duration_seconds=0,
        )
        result = run_pipeline(video_id="test", transcript=empty)
        # Should have errors about no candidates
        assert result.get("errors")


# ── Test: Clip rendering with real video ────────────────────────────────


class TestClipRendering:
    """Test clip cutting and rendering (requires FFmpeg + test video)."""

    @_skip_no_ffmpeg
    @_skip_no_video
    def test_cut_clip(self, tmp_path):
        from app.video_pipeline.render import cut_clip

        output = tmp_path / "cut.mp4"
        cut_clip(TEST_VIDEO, start=0, end=5, output_path=output)
        assert output.exists()
        assert output.stat().st_size > 0

    @_skip_no_ffmpeg
    @_skip_no_video
    def test_crop_to_vertical(self, tmp_path):
        from app.video_pipeline.render import crop_to_vertical

        # First cut a short clip to crop
        from app.video_pipeline.render import cut_clip
        cut = tmp_path / "short.mp4"
        cut_clip(TEST_VIDEO, start=0, end=3, output_path=cut)

        output = tmp_path / "vertical.mp4"
        crop_to_vertical(cut, output)
        assert output.exists()
        assert output.stat().st_size > 0

    @_skip_no_ffmpeg
    @_skip_no_video
    def test_full_render_pipeline(self, tmp_path):
        """Full render from edit plan — cut, crop, normalize, captions."""
        import asyncio
        from app.agents.graph import run_pipeline
        from app.video_pipeline.captions import generate_srt
        from app.video_pipeline.render import render_clip_from_edit_plan
        from app.video_pipeline.transcribe import MockTranscriptionService

        service = MockTranscriptionService()
        transcript = asyncio.run(service.transcribe(Path("/fake/audio.wav")))
        transcript.video_id = "render_test"

        result = run_pipeline(video_id="render_test", transcript=transcript)
        plans = result.get("edit_plans", [])
        assert plans, "No edit plans generated"

        plan = plans[0]
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()

        # Generate SRT
        srt_path = clips_dir / f"{plan.clip_id}.srt"
        clip_segs = [s for s in transcript.segments
                     if s.start_time >= plan.start_time and s.end_time <= plan.end_time]
        if clip_segs:
            generate_srt(clip_segs, srt_path, offset=plan.start_time)

        output = render_clip_from_edit_plan(
            plan, TEST_VIDEO, clips_dir,
            srt_path=srt_path if srt_path.exists() else None,
        )
        assert output.exists()
        assert output.stat().st_size > 0
        # Verify intermediate files were cleaned up
        intermediates = list(clips_dir.glob(f"{plan.clip_id}_*"))
        assert len(intermediates) == 0, f"Intermediate files not cleaned up: {intermediates}"

    @_skip_no_ffmpeg
    @_skip_no_video
    def test_cut_clip_invalid_range(self, tmp_path):
        from app.video_pipeline.render import cut_clip

        with pytest.raises(ValueError, match="Invalid time range"):
            cut_clip(TEST_VIDEO, start=10, end=5, output_path=tmp_path / "out.mp4")

    def test_render_missing_source(self, tmp_path):
        from app.video_pipeline.render import cut_clip

        with pytest.raises(FileNotFoundError):
            cut_clip(Path("/nonexistent.mp4"), start=0, end=5, output_path=tmp_path / "out.mp4")


# ── Test: Config .env resolution ────────────────────────────────────────


class TestConfig:
    """Test that configuration loads correctly."""

    def test_env_file_discovery(self):
        from app.core.config import _find_env_file
        env_path = _find_env_file()
        # Should find the .env at the repo root
        assert Path(env_path).exists() or env_path == ".env"

    def test_settings_load(self):
        from app.core.config import get_settings
        settings = get_settings()
        assert settings.app_name == "ClipForge AI"
        assert settings.max_upload_size_bytes > 0
