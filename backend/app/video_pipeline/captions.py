"""Caption generation – SRT subtitle creation and burn-in.

Supports two SRT generation modes:
1. **Word-level** (``generate_srt_from_words``) — splits word-level timestamps
   into short 2–4 word phrases for modern short-form caption style.
2. **Segment-level** (``generate_srt``) — uses full transcript segments
   (classic SRT). Used as fallback when word-level timestamps are missing.
"""

from __future__ import annotations

import shutil
import subprocess as _subprocess
from functools import lru_cache
from pathlib import Path

from app.core.logging import get_logger
from app.schemas.transcript import TranscriptSegment, WordTimestamp
from app.video_pipeline.audio import _validate_input, run_ffmpeg

logger = get_logger(__name__)


@lru_cache
def _has_subtitles_filter() -> bool:
    """Check whether ffmpeg was built with the ``subtitles`` filter (requires libass)."""
    try:
        result = _subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "subtitles" in result.stdout
    except Exception:
        return False


@lru_cache
def _has_drawtext_filter() -> bool:
    """Check whether ffmpeg was built with the ``drawtext`` filter (requires libfreetype)."""
    try:
        result = _subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Match the word 'drawtext' specifically
        for line in result.stdout.splitlines():
            if "drawtext" in line.split():
                return True
            if " drawtext " in line:
                return True
        return False
    except Exception:
        return False


@lru_cache
def _resolve_system_font() -> str:
    """Return the path to a usable system font for drawtext, or empty string.

    Checks common locations on macOS and Linux.
    """
    candidates = [
        Path("/System/Library/Fonts/Helvetica.ttc"),               # macOS
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),      # macOS fallback
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),  # Debian/Ubuntu
        Path("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"),  # Fedora/RHEL
    ]
    for p in candidates:
        if p.exists():
            logger.info("font_resolved", path=str(p))
            return str(p)

    logger.warning(
        "font_not_resolved",
        hint="No suitable system font found for drawtext. Text may be invisible.",
    )
    return ""


def format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ── Word-level SRT generation (modern short-form style) ──────────────


def _group_words_into_phrases(
    words: list[WordTimestamp],
    max_words: int = 4,
    max_gap: float = 0.8,
) -> list[tuple[float, float, str]]:
    """Group word-level timestamps into short display phrases.

    Returns a list of (start, end, text) tuples.
    """
    if not words:
        return []

    phrases: list[tuple[float, float, str]] = []
    current_words: list[WordTimestamp] = []

    for word in words:
        if current_words and (
            len(current_words) >= max_words
            or (word.start - current_words[-1].end) > max_gap
        ):
            # Flush current phrase
            text = " ".join(w.word.strip() for w in current_words)
            phrases.append((current_words[0].start, current_words[-1].end, text))
            current_words = []

        current_words.append(word)

    # Flush remaining
    if current_words:
        text = " ".join(w.word.strip() for w in current_words)
        phrases.append((current_words[0].start, current_words[-1].end, text))

    return phrases


def generate_srt_from_words(
    segments: list[TranscriptSegment],
    output_path: Path,
    offset: float = 0.0,
    max_words_per_phrase: int = 4,
) -> Path:
    """Generate SRT from word-level timestamps for short-form caption style.

    Each subtitle cue shows 2–4 words at a time, synchronized with speech.
    Falls back to segment-level SRT if no word timestamps are available.

    Args:
        segments: Transcript segments (must have ``.words`` populated).
        output_path: Where to write the .srt file.
        offset: Time offset to subtract (clip start time).
        max_words_per_phrase: Maximum words per subtitle cue.

    Returns:
        Path to the generated SRT file.
    """
    # Collect all words from segments within the time range
    all_words: list[WordTimestamp] = []
    for seg in segments:
        if seg.words:
            all_words.extend(seg.words)

    if not all_words:
        logger.info("srt_word_level_fallback", reason="no word timestamps available")
        return generate_srt(segments, output_path, offset=offset)

    phrases = _group_words_into_phrases(all_words, max_words=max_words_per_phrase)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    index = 0

    for start, end, text in phrases:
        adj_start = max(start - offset, 0)
        adj_end = max(end - offset, 0)

        if adj_end <= adj_start:
            continue

        index += 1
        lines.append(str(index))
        lines.append(f"{format_srt_time(adj_start)} --> {format_srt_time(adj_end)}")
        lines.append(text.upper())  # Upper-case for modern short-form style
        lines.append("")

    if not lines:
        logger.warning("srt_no_phrases_generated", offset=offset, word_count=len(all_words))
        return generate_srt(segments, output_path, offset=offset)

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("srt_word_level_generated", path=str(output_path), cue_count=index)
    return output_path


# ── Segment-level SRT generation (classic fallback) ──────────────────


def generate_srt(
    segments: list[TranscriptSegment],
    output_path: Path,
    offset: float = 0.0,
) -> Path:
    """Generate an SRT subtitle file from transcript segments.

    Args:
        segments: Transcript segments with timestamps.
        output_path: Where to write the .srt file.
        offset: Time offset to subtract (for clips cut from a longer video).

    Returns:
        Path to the generated SRT file.

    Raises:
        ValueError: If *segments* is empty.
    """
    if not segments:
        raise ValueError("Cannot generate SRT from an empty segment list")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    index = 0

    for seg in segments:
        start = max(seg.start_time - offset, 0)
        end = max(seg.end_time - offset, 0)

        if end <= start:
            continue

        index += 1
        text_lines = _wrap_subtitle_text(seg.text, max_chars=42)

        lines.append(str(index))
        lines.append(f"{format_srt_time(start)} --> {format_srt_time(end)}")
        lines.append(text_lines)
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("srt_generated", path=str(output_path), subtitle_count=index)
    return output_path


# ── Caption burn-in ──────────────────────────────────────────────────


def build_caption_filter(
    srt_path: Path,
    font_name: str = "Helvetica",
    font_size: int = 20,
    primary_color: str = "&H00FFFFFF",
    outline_color: str = "&H00000000",
) -> str | None:
    """Build a ``-vf`` filter fragment for caption burn-in.

    Returns the filter string suitable for inclusion in a larger ``-vf`` chain,
    or ``None`` if no caption filter is available in this FFmpeg build.

    The function does **not** run FFmpeg — it only computes the filter string.
    """
    if not srt_path.exists():
        logger.warning("caption_srt_missing", path=str(srt_path))
        return None

    # Strategy 1: subtitles filter (libass) — best quality
    if _has_subtitles_filter():
        logger.info("caption_filter_strategy", method="subtitles_filter")
        srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")
        return (
            f"subtitles='{srt_escaped}'"
            f":force_style='FontName={font_name},FontSize={font_size},"
            f"PrimaryColour={primary_color},OutlineColour={outline_color},"
            f"BorderStyle=4,Outline=1,Shadow=0,"
            f"BackColour=&H80000000,"
            f"MarginV=120,MarginL=40,MarginR=40,"
            f"Alignment=2,Bold=1'"
        )

    # Strategy 2: drawtext filter (libfreetype)
    if _has_drawtext_filter():
        logger.info("caption_filter_strategy", method="drawtext_filter")
        cues = _parse_srt(srt_path)
        if not cues:
            return None

        fontfile = _resolve_system_font()
        fontfile_arg = f":fontfile='{fontfile}'" if fontfile else ""

        filters: list[str] = []
        for start, end, text in cues:
            escaped_text = text.replace("'", "'\\''").replace(":", "\\:").replace(",", "\\,")
            f = (
                f"drawtext=text='{escaped_text}'"
                f"{fontfile_arg}:fontsize={font_size}"
                f":fontcolor=white:borderw=2:bordercolor=black"
                f":x=(w-text_w)/2:y=h-{font_size * 3}"
                f":enable='between(t,{start:.3f},{end:.3f})'"
            )
            filters.append(f)
        return ",".join(filters)

    # Strategy 3: no filter available
    logger.warning(
        "caption_no_filter_available",
        hint=(
            "Neither 'subtitles' (libass) nor 'drawtext' (libfreetype) filters "
            "are available in this FFmpeg build. Captions will be omitted."
        ),
    )
    return None


def burn_captions(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    font_name: str = "Helvetica",
    font_size: int = 20,
    primary_color: str = "&H00FFFFFF",
    outline_color: str = "&H00000000",
) -> Path:
    """Burn SRT captions into a video.

    Tries in order:
    1. ``subtitles`` filter (requires libass) — best quality
    2. ``drawtext`` filter (requires libfreetype) — good quality
    3. Copy without captions — graceful fallback

    Args:
        video_path: Source video.
        srt_path: Path to .srt file.
        output_path: Destination.
        font_name: Font family for subtitles.
        font_size: Font size in pixels.
        primary_color: ASS-format primary colour (``&HAABBGGRR``).
        outline_color: ASS-format outline colour.

    Returns:
        Path to the video with burned captions.
    """
    _validate_input(video_path)
    _validate_input(srt_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Strategy 1: subtitles filter (libass)
    if _has_subtitles_filter():
        logger.info("caption_strategy", method="subtitles_filter")
        srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")

        subtitle_filter = (
            f"subtitles='{srt_escaped}'"
            f":force_style='FontName={font_name},FontSize={font_size},"
            f"PrimaryColour={primary_color},OutlineColour={outline_color},"
            f"BorderStyle=4,Outline=1,Shadow=0,"
            f"BackColour=&H80000000,"
            f"MarginV=120,MarginL=40,MarginR=40,"
            f"Alignment=2,Bold=1'"
        )

        run_ffmpeg([
            "-i", str(video_path),
            "-vf", subtitle_filter,
            "-c:a", "copy",
            str(output_path),
        ])
        return output_path

    # Strategy 2: drawtext filter (libfreetype)
    if _has_drawtext_filter():
        logger.info("caption_strategy", method="drawtext_filter")
        return _burn_captions_drawtext(video_path, srt_path, output_path, font_name, font_size)

    # Strategy 3: fallback — copy without captions
    logger.warning(
        "caption_no_filter_available",
        hint=(
            "Neither 'subtitles' (libass) nor 'drawtext' (libfreetype) filters "
            "are available in this FFmpeg build. Install via: "
            "brew install ffmpeg (with libass/freetype support). "
            "Clips will be produced without burned-in captions."
        ),
    )
    shutil.copy2(video_path, output_path)
    return output_path


def _burn_captions_drawtext(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    font_name: str,
    font_size: int,
) -> Path:
    """Burn captions using the drawtext filter and parsed SRT cues."""
    # Parse SRT into timed text entries
    cues = _parse_srt(srt_path)
    if not cues:
        shutil.copy2(video_path, output_path)
        return output_path

    # Build a complex drawtext filter chain
    filters: list[str] = []
    fontfile = _resolve_system_font()
    fontfile_arg = f":fontfile='{fontfile}'" if fontfile else ""
    for start, end, text in cues:
        escaped_text = text.replace("'", "'\\''").replace(":", "\\:").replace(",", "\\,")
        f = (
            f"drawtext=text='{escaped_text}'"
            f"{fontfile_arg}:fontsize={font_size}"
            f":fontcolor=white:borderw=2:bordercolor=black"
            f":x=(w-text_w)/2:y=h-{font_size * 3}"
            f":enable='between(t,{start:.3f},{end:.3f})'"
        )
        filters.append(f)

    filter_str = ",".join(filters)
    run_ffmpeg([
        "-i", str(video_path),
        "-vf", filter_str,
        "-c:a", "copy",
        str(output_path),
    ])
    return output_path


def _parse_srt(srt_path: Path) -> list[tuple[float, float, str]]:
    """Parse an SRT file into (start_seconds, end_seconds, text) tuples."""
    content = srt_path.read_text(encoding="utf-8")
    cues: list[tuple[float, float, str]] = []

    blocks = content.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        # Line 2 is the timestamp
        ts_line = lines[1]
        parts = ts_line.split(" --> ")
        if len(parts) != 2:
            continue
        start = _srt_time_to_seconds(parts[0].strip())
        end = _srt_time_to_seconds(parts[1].strip())
        text = " ".join(lines[2:]).strip()
        cues.append((start, end, text))

    return cues


def _srt_time_to_seconds(ts: str) -> float:
    """Convert ``HH:MM:SS,mmm`` to float seconds."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if len(parts) != 3:
        return 0.0
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def _wrap_subtitle_text(text: str, max_chars: int = 42) -> str:
    """Wrap text into subtitle-friendly lines."""
    words = text.split()
    lines: list[str] = []
    current_line: list[str] = []
    current_length = 0

    for word in words:
        if current_length + len(word) + 1 > max_chars and current_line:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_length = len(word)
        else:
            current_line.append(word)
            current_length += len(word) + (1 if current_length > 0 else 0)

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)
