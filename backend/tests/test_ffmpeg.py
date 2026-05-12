"""Tests for video_pipeline: audio, render, and captions modules."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.errors import FFmpegError
from app.schemas.clip import ClipScore, EditPlan
from app.schemas.transcript import TranscriptSegment
from app.video_pipeline.audio import (
    check_ffmpeg_available,
    extract_audio,
    normalize_audio,
    run_ffmpeg,
)
from app.video_pipeline.captions import (
    burn_captions,
    build_caption_filter,
    format_srt_time,
    generate_srt,
    generate_srt_from_words,
    _group_words_into_phrases,
    _parse_srt,
    _resolve_system_font,
    _srt_time_to_seconds,
)
from app.video_pipeline.crop import (
    CropRegion,
    CropStrategy,
    compute_crop_region,
)
from app.video_pipeline.render import (
    _assert_has_audio_and_video,
    crop_to_vertical,
    cut_clip,
    render_clip_from_edit_plan,
)
from app.schemas.transcript import WordTimestamp


# ── Helpers ──────────────────────────────────────────────


def _make_video(tmp_path: Path, name: str = "test.mp4") -> Path:
    """Create a dummy video file on disk."""
    f = tmp_path / name
    f.write_bytes(b"\x00" * 16)
    return f


def _make_srt(tmp_path: Path, name: str = "test.srt") -> Path:
    """Create a minimal SRT file on disk."""
    f = tmp_path / name
    f.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n\n")
    return f


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
# audio.py
# ═══════════════════════════════════════════════════════════


class TestCheckFFmpegAvailable:
    @patch("shutil.which", return_value="/usr/bin/ffmpeg")
    def test_found(self, mock_which):
        assert check_ffmpeg_available() is True
        mock_which.assert_called_once_with("ffmpeg")

    @patch("shutil.which", return_value=None)
    def test_not_found(self, mock_which):
        assert check_ffmpeg_available() is False


class TestRunFFmpeg:
    @patch("subprocess.run")
    def test_successful_command(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg", "-y", "-version"],
            returncode=0,
            stdout="ffmpeg version 6.0",
            stderr="",
        )
        result = run_ffmpeg(["-version"])
        assert result.returncode == 0
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_failed_command_raises_ffmpeg_error(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg", "-y", "-i", "bad.mp4"],
            returncode=1,
            stdout="",
            stderr="No such file or directory",
        )
        with pytest.raises(FFmpegError):
            run_ffmpeg(["-i", "bad.mp4"])

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_ffmpeg_not_installed(self, mock_run):
        with pytest.raises(FFmpegError, match="not installed"):
            run_ffmpeg(["-version"])

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10))
    def test_timeout(self, mock_run):
        with pytest.raises(FFmpegError, match="timed out"):
            run_ffmpeg(["-i", "long.mp4"], timeout=10)

    @patch("subprocess.run")
    def test_no_shell_true(self, mock_run):
        """Ensure subprocess is never invoked with shell=True."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        run_ffmpeg(["-version"])
        _, kwargs = mock_run.call_args
        assert kwargs.get("shell") is not True


class TestExtractAudio:
    @patch("app.video_pipeline.audio.run_ffmpeg")
    def test_creates_output_dir_and_calls_ffmpeg(self, mock_ffmpeg, tmp_path):
        video = _make_video(tmp_path)
        output = tmp_path / "sub" / "audio.wav"

        extract_audio(video, output)

        assert output.parent.exists()
        mock_ffmpeg.assert_called_once()
        args = mock_ffmpeg.call_args[0][0]
        assert "-vn" in args
        assert "-ar" in args
        assert "16000" in args
        assert "-ac" in args

    def test_missing_input_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="does not exist"):
            extract_audio(tmp_path / "missing.mp4", tmp_path / "out.wav")


class TestNormalizeAudio:
    @patch("app.video_pipeline.audio.run_ffmpeg")
    def test_calls_loudnorm_filter(self, mock_ffmpeg, tmp_path):
        audio = _make_video(tmp_path, "audio.wav")
        output = tmp_path / "norm.wav"

        normalize_audio(audio, output)

        args = mock_ffmpeg.call_args[0][0]
        af_index = args.index("-af")
        assert "loudnorm" in args[af_index + 1]

    def test_missing_input_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            normalize_audio(tmp_path / "missing.wav", tmp_path / "out.wav")


# ═══════════════════════════════════════════════════════════
# captions.py
# ═══════════════════════════════════════════════════════════


class TestFormatSrtTime:
    def test_zero(self):
        assert format_srt_time(0) == "00:00:00,000"

    def test_simple_seconds(self):
        assert format_srt_time(5.5) == "00:00:05,500"

    def test_minutes_and_seconds(self):
        assert format_srt_time(125.25) == "00:02:05,250"

    def test_hours(self):
        assert format_srt_time(3661.0) == "01:01:01,000"


class TestGenerateSrt:
    def test_generates_valid_srt(self, tmp_path):
        segments = [
            TranscriptSegment(start_time=0.0, end_time=2.5, text="Hello world"),
            TranscriptSegment(start_time=3.0, end_time=6.0, text="Second line"),
        ]
        out = tmp_path / "test.srt"
        result = generate_srt(segments, out)

        assert result == out
        content = out.read_text()
        assert "00:00:00,000 --> 00:00:02,500" in content
        assert "Hello world" in content
        assert "Second line" in content

    def test_offset_subtracts_from_times(self, tmp_path):
        segments = [
            TranscriptSegment(start_time=10.0, end_time=15.0, text="Offset test"),
        ]
        out = tmp_path / "offset.srt"
        generate_srt(segments, out, offset=10.0)

        content = out.read_text()
        assert "00:00:00,000 --> 00:00:05,000" in content

    def test_skips_segments_where_end_lte_start_after_offset(self, tmp_path):
        segments = [
            TranscriptSegment(start_time=1.0, end_time=2.0, text="Before offset"),
            TranscriptSegment(start_time=5.0, end_time=8.0, text="After offset"),
        ]
        out = tmp_path / "skip.srt"
        generate_srt(segments, out, offset=5.0)

        content = out.read_text()
        assert "Before offset" not in content
        assert "After offset" in content

    def test_empty_segments_raises(self, tmp_path):
        with pytest.raises(ValueError, match="empty"):
            generate_srt([], tmp_path / "empty.srt")

    def test_creates_parent_directories(self, tmp_path):
        segments = [
            TranscriptSegment(start_time=0, end_time=1, text="deep"),
        ]
        out = tmp_path / "a" / "b" / "deep.srt"
        generate_srt(segments, out)
        assert out.exists()


class TestBurnCaptions:
    @patch("app.video_pipeline.captions._has_subtitles_filter", return_value=True)
    @patch("app.video_pipeline.captions.run_ffmpeg")
    def test_calls_subtitles_filter(self, mock_ffmpeg, _mock_filter, tmp_path):
        video = _make_video(tmp_path)
        srt = _make_srt(tmp_path)
        output = tmp_path / "captioned.mp4"

        burn_captions(video, srt, output)

        mock_ffmpeg.assert_called_once()
        args = mock_ffmpeg.call_args[0][0]
        assert "-vf" in args
        vf_value = args[args.index("-vf") + 1]
        assert "subtitles=" in vf_value

    @patch("app.video_pipeline.captions._has_subtitles_filter", return_value=True)
    @patch("app.video_pipeline.captions.run_ffmpeg")
    def test_custom_font_applied(self, mock_ffmpeg, _mock_filter, tmp_path):
        video = _make_video(tmp_path)
        srt = _make_srt(tmp_path)

        burn_captions(video, srt, tmp_path / "out.mp4", font_name="Poppins")

        vf_value = mock_ffmpeg.call_args[0][0][mock_ffmpeg.call_args[0][0].index("-vf") + 1]
        assert "Poppins" in vf_value

    @patch("app.video_pipeline.captions._has_subtitles_filter", return_value=False)
    def test_skips_burn_when_no_libass(self, _mock_filter, tmp_path):
        video = _make_video(tmp_path)
        srt = _make_srt(tmp_path)
        output = tmp_path / "out.mp4"

        result = burn_captions(video, srt, output)

        assert result == output
        assert output.exists()
        # Output should be a copy of the input, not a captioned version
        assert output.read_bytes() == video.read_bytes()

    def test_missing_video_raises(self, tmp_path):
        srt = _make_srt(tmp_path)
        with pytest.raises(FileNotFoundError):
            burn_captions(tmp_path / "missing.mp4", srt, tmp_path / "out.mp4")

    def test_missing_srt_raises(self, tmp_path):
        video = _make_video(tmp_path)
        with pytest.raises(FileNotFoundError):
            burn_captions(video, tmp_path / "missing.srt", tmp_path / "out.mp4")


class TestBuildCaptionFilter:
    @patch("app.video_pipeline.captions._has_subtitles_filter", return_value=True)
    def test_returns_subtitles_filter(self, _mock, tmp_path):
        srt = _make_srt(tmp_path)
        result = build_caption_filter(srt)
        assert result is not None
        assert "subtitles=" in result

    @patch("app.video_pipeline.captions._has_subtitles_filter", return_value=False)
    @patch("app.video_pipeline.captions._has_drawtext_filter", return_value=False)
    def test_returns_none_when_no_filters(self, _mock1, _mock2, tmp_path):
        srt = _make_srt(tmp_path)
        result = build_caption_filter(srt)
        assert result is None

    def test_returns_none_for_missing_srt(self, tmp_path):
        result = build_caption_filter(tmp_path / "missing.srt")
        assert result is None

    @patch("app.video_pipeline.captions._has_subtitles_filter", return_value=False)
    @patch("app.video_pipeline.captions._has_drawtext_filter", return_value=True)
    @patch("app.video_pipeline.captions._resolve_system_font", return_value="/usr/share/fonts/test.ttf")
    def test_drawtext_uses_resolved_font(self, _mock_font, _mock_dt, _mock_sub, tmp_path):
        srt = _make_srt(tmp_path)
        result = build_caption_filter(srt)
        assert result is not None
        assert "drawtext=" in result
        assert "/usr/share/fonts/test.ttf" in result


class TestResolveSystemFont:
    @patch("pathlib.Path.exists", return_value=False)
    def test_returns_empty_when_no_fonts(self, _mock):
        _resolve_system_font.cache_clear()
        result = _resolve_system_font()
        assert result == ""
        _resolve_system_font.cache_clear()


# ═══════════════════════════════════════════════════════════
# render.py
# ═══════════════════════════════════════════════════════════


class TestCutClip:
    @patch("app.video_pipeline.render.run_ffmpeg")
    def test_passes_ss_and_t_flags(self, mock_ffmpeg, tmp_path):
        video = _make_video(tmp_path)
        output = tmp_path / "clip.mp4"

        cut_clip(video, 10.0, 25.0, output)

        args = mock_ffmpeg.call_args[0][0]
        assert "-ss" in args
        assert "10.0" in args
        assert "-t" in args
        assert "15.0" in args  # duration = 25 - 10

    def test_missing_input_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            cut_clip(tmp_path / "missing.mp4", 0, 5, tmp_path / "out.mp4")

    def test_invalid_time_range_raises(self, tmp_path):
        video = _make_video(tmp_path)
        with pytest.raises(ValueError, match="Invalid time range"):
            cut_clip(video, 10.0, 5.0, tmp_path / "out.mp4")

    def test_negative_start_raises(self, tmp_path):
        video = _make_video(tmp_path)
        with pytest.raises(ValueError, match="Invalid time range"):
            cut_clip(video, -1.0, 5.0, tmp_path / "out.mp4")

    @patch("app.video_pipeline.render.run_ffmpeg")
    def test_creates_output_directory(self, mock_ffmpeg, tmp_path):
        video = _make_video(tmp_path)
        output = tmp_path / "deep" / "clip.mp4"
        cut_clip(video, 0, 10, output)
        assert output.parent.exists()


class TestCropToVertical:
    @patch("app.video_pipeline.render.run_ffmpeg")
    def test_applies_crop_and_scale_filter(self, mock_ffmpeg, tmp_path):
        video = _make_video(tmp_path)
        output = tmp_path / "vertical.mp4"

        crop_to_vertical(video, output)

        args = mock_ffmpeg.call_args[0][0]
        vf_value = args[args.index("-vf") + 1]
        assert "crop=ih*9/16:ih" in vf_value
        assert "scale=1080:1920" in vf_value

    def test_missing_input_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            crop_to_vertical(tmp_path / "missing.mp4", tmp_path / "out.mp4")


class TestRenderClipFromEditPlan:
    @patch("app.video_pipeline.render._assert_has_audio_and_video")
    @patch("app.video_pipeline.render.build_caption_filter", return_value=None)
    @patch("app.video_pipeline.render._try_detect_face_center", return_value=None)
    @patch("app.video_pipeline.render.probe_video_dimensions", return_value=(2560, 1440))
    @patch("app.video_pipeline.render.run_ffmpeg")
    def test_single_pass_without_srt(self, mock_ffmpeg, mock_probe, mock_face, mock_cap, mock_assert, tmp_path):
        video = _make_video(tmp_path, "source.mp4")
        output_dir = tmp_path / "output"

        plan = EditPlan(
            clip_id="clip_001",
            source_video_id="vid_001",
            start_time=5.0,
            end_time=35.0,
            score=_default_score(),
        )

        # Simulate FFmpeg creating the output file
        def create_file_side_effect(args, *a, **kw):
            out = Path(args[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00")
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        mock_ffmpeg.side_effect = create_file_side_effect

        result = render_clip_from_edit_plan(plan, video, output_dir)

        assert result.name == "clip_001.mp4"
        # Single FFmpeg call — no intermediate files
        mock_ffmpeg.assert_called_once()
        args = mock_ffmpeg.call_args[0][0]
        # Verify fast-seek + accurate-seek pattern
        assert args[0:2] == ["-ss", "5.0"]
        assert "-map" in args
        assert "0:v:0" in args
        assert "0:a:0?" in args
        # Verify re-encoded audio
        assert "-c:a" in args
        ca_idx = args.index("-c:a")
        assert args[ca_idx + 1] == "aac"
        # Verify crop filter is present
        vf_idx = args.index("-vf")
        assert "crop=" in args[vf_idx + 1]
        assert "scale=1080:1920" in args[vf_idx + 1]
        # Verify loudnorm (normalize is True by default)
        assert "-af" in args
        af_idx = args.index("-af")
        assert "loudnorm" in args[af_idx + 1]
        # Verify compatibility flags
        assert "-pix_fmt" in args
        assert "-movflags" in args
        assert "-avoid_negative_ts" in args

        mock_assert.assert_called_once()
        mock_probe.assert_called_once()

    @patch("app.video_pipeline.render._assert_has_audio_and_video")
    @patch("app.video_pipeline.render.build_caption_filter", return_value="subtitles='test.srt'")
    @patch("app.video_pipeline.render._try_detect_face_center", return_value=None)
    @patch("app.video_pipeline.render.probe_video_dimensions", return_value=(1920, 1080))
    @patch("app.video_pipeline.render.run_ffmpeg")
    def test_single_pass_with_srt(self, mock_ffmpeg, mock_probe, mock_face, mock_cap, mock_assert, tmp_path):
        video = _make_video(tmp_path, "source.mp4")
        output_dir = tmp_path / "output"
        srt = _make_srt(tmp_path, "clip.srt")

        plan = EditPlan(
            clip_id="clip_002",
            source_video_id="vid_001",
            start_time=10.0,
            end_time=40.0,
            score=_default_score(),
        )

        def create_file_side_effect(args, *a, **kw):
            out = Path(args[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00")
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        mock_ffmpeg.side_effect = create_file_side_effect

        result = render_clip_from_edit_plan(plan, video, output_dir, srt_path=srt)

        assert result.name == "clip_002.mp4"
        mock_ffmpeg.assert_called_once()
        args = mock_ffmpeg.call_args[0][0]
        # Verify caption filter is included in the vf chain
        vf_idx = args.index("-vf")
        assert "subtitles=" in args[vf_idx + 1]

    @patch("app.video_pipeline.render._assert_has_audio_and_video")
    @patch("app.video_pipeline.render._try_detect_face_center", return_value=None)
    @patch("app.video_pipeline.render.probe_video_dimensions", return_value=(2560, 1440))
    @patch("app.video_pipeline.render.run_ffmpeg")
    def test_no_normalize_skips_af(self, mock_ffmpeg, mock_probe, mock_face, mock_assert, tmp_path):
        """When audio normalize is disabled, no -af flag should be present."""
        from app.schemas.clip import AudioSettings

        video = _make_video(tmp_path, "source.mp4")
        output_dir = tmp_path / "output"

        plan = EditPlan(
            clip_id="clip_003",
            source_video_id="vid_001",
            start_time=0.0,
            end_time=20.0,
            score=_default_score(),
            audio=AudioSettings(normalize=False),
        )

        def create_file_side_effect(args, *a, **kw):
            out = Path(args[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00")
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        mock_ffmpeg.side_effect = create_file_side_effect

        result = render_clip_from_edit_plan(plan, video, output_dir)

        assert result.name == "clip_003.mp4"
        args = mock_ffmpeg.call_args[0][0]
        assert "-af" not in args

    def test_missing_source_raises(self, tmp_path):
        plan = EditPlan(
            clip_id="clip_x",
            source_video_id="vid_x",
            start_time=0,
            end_time=10,
            score=_default_score(),
        )
        with pytest.raises(FileNotFoundError):
            render_clip_from_edit_plan(plan, tmp_path / "missing.mp4", tmp_path / "out")


# ── Assert has audio and video ────────────────────────────────────────


class TestAssertHasAudioAndVideo:
    @patch("subprocess.run")
    def test_both_streams_pass(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"streams":[{"codec_type":"video"},{"codec_type":"audio"}]}', stderr="",
        )
        video = _make_video(tmp_path)
        _assert_has_audio_and_video(video)  # should not raise

    @patch("subprocess.run")
    def test_missing_audio_raises(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"streams":[{"codec_type":"video"}]}', stderr="",
        )
        video = _make_video(tmp_path)
        with pytest.raises(FFmpegError, match="missing an audio stream"):
            _assert_has_audio_and_video(video)

    @patch("subprocess.run")
    def test_missing_video_raises(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"streams":[{"codec_type":"audio"}]}', stderr="",
        )
        video = _make_video(tmp_path)
        with pytest.raises(FFmpegError, match="missing a video stream"):
            _assert_has_audio_and_video(video)

    @patch("subprocess.run")
    def test_empty_streams_raises(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"streams":[]}', stderr="",
        )
        video = _make_video(tmp_path)
        with pytest.raises(FFmpegError):
            _assert_has_audio_and_video(video)

    @patch("subprocess.run")
    def test_ffprobe_failure_raises(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="ffprobe error",
        )
        video = _make_video(tmp_path)
        with pytest.raises(FFmpegError, match="ffprobe error"):
            _assert_has_audio_and_video(video)


# ── Smart Crop Tests ─────────────────────────────────────────────────


class TestComputeCropRegion:
    def test_landscape_center_crop(self):
        """Standard landscape video → 9:16 center crop."""
        region = compute_crop_region(2560, 1440)
        assert region.strategy == CropStrategy.PROBE_CENTER
        assert region.h == 1440
        assert region.w == 810  # 1440 * 9 / 16
        assert region.scale_w == 1080
        assert region.scale_h == 1920
        # Centered
        assert region.x == (2560 - 810) // 2

    def test_1080p_landscape(self):
        """1920×1080 → 9:16."""
        region = compute_crop_region(1920, 1080)
        assert region.w == 607  # 1080 * 9 / 16
        assert region.h == 1080

    def test_face_center_shifts_crop(self):
        """Face position biases the crop toward the face."""
        # Face on the left third
        region_left = compute_crop_region(2560, 1440, face_center=(400, 720))
        assert region_left.strategy == CropStrategy.FACE_DETECT
        assert region_left.x < (2560 - 810) // 2  # Should be left of center

        # Face on the right third
        region_right = compute_crop_region(2560, 1440, face_center=(2200, 720))
        assert region_right.strategy == CropStrategy.FACE_DETECT
        assert region_right.x > (2560 - 810) // 2  # Should be right of center

    def test_face_center_clamped_to_bounds(self):
        """Face at extreme edge shouldn't produce negative crop coords."""
        region = compute_crop_region(2560, 1440, face_center=(0, 720))
        assert region.x >= 0
        assert region.x + region.w <= 2560

        region2 = compute_crop_region(2560, 1440, face_center=(2560, 720))
        assert region2.x >= 0
        assert region2.x + region2.w <= 2560

    def test_already_portrait(self):
        """Portrait input → passthrough (no crop)."""
        region = compute_crop_region(1080, 1920)
        assert region.strategy == CropStrategy.PASSTHROUGH

    def test_square_source(self):
        """Square video → crop to 9:16."""
        region = compute_crop_region(1080, 1080)
        assert region.w == 607  # 1080 * 9 / 16
        assert region.h == 1080

    def test_crop_region_vf_string(self):
        region = CropRegion(x=875, y=0, w=810, h=1440, scale_w=1080, scale_h=1920, strategy=CropStrategy.PROBE_CENTER)
        assert region.vf_string == "crop=810:1440:875:0,scale=1080:1920"


# ── Word-level SRT Tests ─────────────────────────────────────────────


class TestWordLevelSRT:
    def test_group_words_basic(self):
        words = [
            WordTimestamp(word="Hello", start=0.0, end=0.3),
            WordTimestamp(word="world", start=0.4, end=0.7),
            WordTimestamp(word="how", start=0.8, end=1.0),
            WordTimestamp(word="are", start=1.1, end=1.3),
            WordTimestamp(word="you", start=1.4, end=1.6),
            WordTimestamp(word="today", start=1.7, end=2.0),
        ]
        phrases = _group_words_into_phrases(words, max_words=3)
        assert len(phrases) == 2
        assert phrases[0] == (0.0, 1.0, "Hello world how")
        assert phrases[1] == (1.1, 2.0, "are you today")

    def test_group_words_gap_splits(self):
        """Long gaps between words should force a new phrase."""
        words = [
            WordTimestamp(word="Hello", start=0.0, end=0.3),
            WordTimestamp(word="world", start=2.0, end=2.3),  # 1.7s gap
        ]
        phrases = _group_words_into_phrases(words, max_words=4, max_gap=0.8)
        assert len(phrases) == 2

    def test_group_words_empty(self):
        assert _group_words_into_phrases([]) == []

    def test_generate_srt_from_words_creates_file(self, tmp_path):
        segments = [
            TranscriptSegment(
                start_time=10.0,
                end_time=12.0,
                text="Hello world how are you today",
                words=[
                    WordTimestamp(word="Hello", start=10.0, end=10.3),
                    WordTimestamp(word="world", start=10.4, end=10.7),
                    WordTimestamp(word="how", start=10.8, end=11.0),
                    WordTimestamp(word="are", start=11.1, end=11.3),
                    WordTimestamp(word="you", start=11.4, end=11.6),
                    WordTimestamp(word="today", start=11.7, end=12.0),
                ],
            )
        ]
        srt_path = tmp_path / "test.srt"
        result = generate_srt_from_words(segments, srt_path, offset=10.0)
        assert result.exists()
        content = result.read_text()
        # Should have upper-case text
        assert "HELLO" in content
        # Should have proper SRT format
        assert " --> " in content

    def test_generate_srt_from_words_falls_back_without_words(self, tmp_path):
        """When segments have no word-level timestamps, falls back to segment SRT."""
        segments = [
            TranscriptSegment(start_time=0.0, end_time=5.0, text="Hello world"),
        ]
        srt_path = tmp_path / "test.srt"
        result = generate_srt_from_words(segments, srt_path, offset=0.0)
        assert result.exists()
        content = result.read_text()
        assert "Hello world" in content


class TestSRTParsing:
    def test_parse_srt_roundtrip(self, tmp_path):
        """SRT generated by generate_srt should be parseable by _parse_srt."""
        segments = [
            TranscriptSegment(start_time=0.0, end_time=2.0, text="First line"),
            TranscriptSegment(start_time=3.0, end_time=5.0, text="Second line"),
        ]
        srt_path = tmp_path / "test.srt"
        generate_srt(segments, srt_path)

        cues = _parse_srt(srt_path)
        assert len(cues) == 2
        assert cues[0][2] == "First line"
        assert cues[1][2] == "Second line"

    def test_srt_time_to_seconds(self):
        assert _srt_time_to_seconds("00:01:30,500") == 90.5
        assert _srt_time_to_seconds("01:00:00,000") == 3600.0
        assert _srt_time_to_seconds("00:00:00,000") == 0.0
