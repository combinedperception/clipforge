"""FFmpeg audio extraction and normalization."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.core.errors import FFmpegError
from app.core.logging import get_logger

logger = get_logger(__name__)


def _validate_input(path: Path) -> None:
    """Raise FileNotFoundError if *path* does not exist."""
    if not path.is_file():
        raise FileNotFoundError(f"Input file does not exist: {path}")


def check_ffmpeg_available() -> bool:
    """Return True if FFmpeg is available on the system PATH."""
    return shutil.which("ffmpeg") is not None


# Keep the old name as an alias for backwards compatibility.
check_ffmpeg_installed = check_ffmpeg_available


def run_ffmpeg(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    """Execute an FFmpeg command with proper error handling.

    Args:
        args: FFmpeg arguments (without the leading 'ffmpeg').
        timeout: Maximum seconds to wait.

    Returns:
        CompletedProcess on success.

    Raises:
        FFmpegError: If the command fails.
    """
    cmd = ["ffmpeg", "-y", *args]
    cmd_str = " ".join(cmd)
    logger.info("ffmpeg_start", command=cmd_str)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise FFmpegError(cmd_str, "FFmpeg is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        raise FFmpegError(cmd_str, f"FFmpeg timed out after {timeout}s.")

    if result.returncode != 0:
        logger.error("ffmpeg_failed", command=cmd_str, stderr=result.stderr[:1000])
        raise FFmpegError(cmd_str, result.stderr)

    logger.info("ffmpeg_success", command=cmd_str)
    return result


def extract_audio(video_path: Path, output_path: Path) -> Path:
    """Extract audio track from video as WAV.

    Args:
        video_path: Path to the source video.
        output_path: Destination path for the audio file.

    Returns:
        Path to the extracted audio.

    Raises:
        FileNotFoundError: If *video_path* does not exist.
        FFmpegError: If the FFmpeg command fails.
    """
    _validate_input(video_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_path),
    ])
    return output_path


def normalize_audio(audio_path: Path, output_path: Path) -> Path:
    """Normalize audio loudness using the loudnorm filter.

    Args:
        audio_path: Path to the input audio.
        output_path: Destination path.

    Returns:
        Path to normalized audio.

    Raises:
        FileNotFoundError: If *audio_path* does not exist.
        FFmpegError: If the FFmpeg command fails.
    """
    _validate_input(audio_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(audio_path),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        str(output_path),
    ])
    return output_path
