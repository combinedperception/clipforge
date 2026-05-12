"""FFmpeg-based video rendering from structured edit plans."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.core.errors import FFmpegError
from app.core.logging import get_logger
from app.schemas.clip import EditPlan
from app.video_pipeline.audio import _validate_input, normalize_audio, run_ffmpeg
from app.video_pipeline.captions import build_caption_filter, burn_captions
from app.video_pipeline.crop import (
    CropRegion,
    CropStrategy,
    _try_detect_face_center,
    compute_crop_region,
    probe_video_dimensions,
    smart_crop_to_vertical,
)

logger = get_logger(__name__)


def _assert_has_audio_and_video(path: Path) -> None:
    """Verify that *path* contains at least one audio and one video stream.

    Raises:
        FFmpegError: If either stream type is missing.
    """
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise FFmpegError(
            f"ffprobe {path}",
            result.stderr or "ffprobe returned non-zero exit code",
        )

    data = json.loads(result.stdout)
    codec_types = {s.get("codec_type") for s in data.get("streams", [])}

    if "video" not in codec_types:
        raise FFmpegError(f"ffprobe {path}", "Output file is missing a video stream")
    if "audio" not in codec_types:
        raise FFmpegError(f"ffprobe {path}", "Output file is missing an audio stream")


def cut_clip(video_path: Path, start: float, end: float, output_path: Path) -> Path:
    """Cut a segment from a video file.

    Args:
        video_path: Source video.
        start: Start time in seconds.
        end: End time in seconds.
        output_path: Destination.

    Returns:
        Path to the cut clip.

    Raises:
        FileNotFoundError: If *video_path* does not exist.
        ValueError: If time range is invalid.
        FFmpegError: If the FFmpeg command fails.
    """
    _validate_input(video_path)
    if start < 0 or end <= start:
        raise ValueError(f"Invalid time range: start={start}, end={end}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = end - start
    run_ffmpeg([
        "-ss", str(start),
        "-i", str(video_path),
        "-t", str(duration),
        "-c", "copy",
        str(output_path),
    ])
    return output_path


def crop_to_vertical(video_path: Path, output_path: Path) -> Path:
    """Crop video to 9:16 vertical format (center crop).

    Args:
        video_path: Source video.
        output_path: Destination.

    Returns:
        Path to the cropped video.

    Raises:
        FileNotFoundError: If *video_path* does not exist.
        FFmpegError: If the FFmpeg command fails.
    """
    _validate_input(video_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(video_path),
        "-vf", "crop=ih*9/16:ih,scale=1080:1920",
        "-c:a", "copy",
        str(output_path),
    ])
    return output_path


def render_clip_from_edit_plan(
    edit_plan: EditPlan,
    source_video_path: Path,
    output_dir: Path,
    srt_path: Path | None = None,
) -> Path:
    """Execute a single-pass render pipeline from an EditPlan.

    Produces the final clip in one FFmpeg invocation:
    cut + crop + audio normalize + caption burn-in.

    Uses the "fast seek + accurate seek" pattern so timestamps are precise
    and audio is always re-encoded to avoid stream-copy desync.

    Args:
        edit_plan: Structured edit plan.
        source_video_path: Path to the source video.
        output_dir: Directory for output files.
        srt_path: Optional path to SRT subtitles.

    Returns:
        Path to the final rendered clip.

    Raises:
        FileNotFoundError: If *source_video_path* does not exist.
        FFmpegError: If the FFmpeg command fails or the output lacks streams.
    """
    _validate_input(source_video_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    clip_id = edit_plan.clip_id
    duration = edit_plan.end_time - edit_plan.start_time

    logger.info("render_start", clip_id=clip_id, start=edit_plan.start_time, end=edit_plan.end_time)

    # ── Build video filter chain ──────────────────────────

    vf_parts: list[str] = []

    # Crop to vertical (9:16)
    crop_region: CropRegion | None = None
    if edit_plan.format.value == "vertical_9_16":
        try:
            src_w, src_h = probe_video_dimensions(source_video_path)
            face_center = _try_detect_face_center(source_video_path)
            crop_region = compute_crop_region(src_w, src_h, face_center=face_center)
            vf_parts.append(crop_region.vf_string)
            logger.info(
                "render_crop_result",
                clip_id=clip_id,
                strategy=crop_region.strategy.value,
                crop=crop_region.vf_string,
            )
        except Exception as exc:
            logger.warning("crop_probe_failed", clip_id=clip_id, error=str(exc))
            vf_parts.append("crop=ih*9/16:ih,scale=1080:1920")
            crop_region = CropRegion(
                x=0, y=0, w=0, h=0,
                scale_w=1080, scale_h=1920,
                strategy=CropStrategy.CENTER,
            )

    # Captions
    if srt_path and srt_path.exists():
        style = edit_plan.caption_style
        caption_vf = build_caption_filter(
            srt_path,
            font_name=style.font,
            primary_color=style.primary_color,
        )
        if caption_vf:
            vf_parts.append(caption_vf)

    # ── Build audio filter chain ──────────────────────────

    af_parts: list[str] = []
    if edit_plan.audio.normalize:
        af_parts.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    # ── Assemble single FFmpeg command ────────────────────

    final_path = output_dir / f"{clip_id}.mp4"

    cmd: list[str] = [
        # Fast seek (keyframe-level) before input
        "-ss", str(edit_plan.start_time),
        "-i", str(source_video_path),
        # Accurate seek (frame-level) after input
        "-ss", "0",
        "-t", str(duration),
        # Stream mapping — '?' makes audio optional so ffmpeg won't
        # crash on sources that truly have no audio track.
        "-map", "0:v:0",
        "-map", "0:a:0?",
    ]

    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])

    if af_parts:
        cmd.extend(["-af", ",".join(af_parts)])

    cmd.extend([
        # Always re-encode audio to avoid stream-copy desync
        "-c:v", "libx264",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-avoid_negative_ts", "make_zero",
        str(final_path),
    ])

    run_ffmpeg(cmd)

    # Verify the output has both streams
    _assert_has_audio_and_video(final_path)

    logger.info("render_complete", clip_id=clip_id, output=str(final_path))
    return final_path
