"""Smart video cropping — subject-aware crop for vertical (9:16) output.

Strategies (ordered by quality):
1. **face_detect** — OpenCV Haar cascade face detection, crop centered on detected face(s)
2. **probe_center** — Use ffprobe to determine frame dimensions, center-crop with bias
   toward the lower-third (where speakers typically sit in presentation layouts)
3. **center** — Simple center crop (fallback)

The strategy is selected automatically: face_detect if OpenCV is available and
a face is found, otherwise probe_center. ``center`` is only used if ffprobe fails.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.core.logging import get_logger
from app.video_pipeline.audio import _validate_input, run_ffmpeg

logger = get_logger(__name__)


class CropStrategy(str, Enum):
    """Which strategy was used to determine the crop region."""

    FACE_DETECT = "face_detect"
    PROBE_CENTER = "probe_center"
    CENTER = "center"
    PASSTHROUGH = "passthrough"


@dataclass
class CropRegion:
    """Describes a crop rectangle and target scale."""

    x: int
    y: int
    w: int
    h: int
    scale_w: int
    scale_h: int
    strategy: CropStrategy

    @property
    def vf_string(self) -> str:
        """Return the FFmpeg ``-vf`` filter string for this crop."""
        return f"crop={self.w}:{self.h}:{self.x}:{self.y},scale={self.scale_w}:{self.scale_h}"


def probe_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError("No video stream found")

    return int(streams[0]["width"]), int(streams[0]["height"])


# ── Face detection helper ─────────────────────────────────────────────


def _try_detect_face_center(video_path: Path) -> tuple[int, int] | None:
    """Attempt to detect a face in the video and return its (x, y) center.

    Uses OpenCV Haar cascade on a frame from 1 second into the video.
    Returns None if OpenCV is unavailable or no face is found.
    """
    try:
        import cv2
    except ImportError:
        logger.info("crop_opencv_unavailable", hint="pip install opencv-python-headless for face detection")
        return None

    # Extract a frame at ~1 second
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    # Seek to 1 second
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps))
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return None

    # Convert to grayscale for detection
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Use frontal face cascade
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))

    if len(faces) == 0:
        logger.info("crop_no_faces_detected", video=str(video_path))
        return None

    # Use the largest detected face
    largest = max(faces, key=lambda f: f[2] * f[3])
    fx, fy, fw, fh = largest
    center_x = fx + fw // 2
    center_y = fy + fh // 2

    logger.info(
        "crop_face_detected",
        face_center_x=center_x,
        face_center_y=center_y,
        face_size=f"{fw}x{fh}",
        frame_size=f"{frame.shape[1]}x{frame.shape[0]}",
    )
    return center_x, center_y


# ── Crop computation ──────────────────────────────────────────────────


def compute_crop_region(
    src_w: int,
    src_h: int,
    target_w: int = 1080,
    target_h: int = 1920,
    face_center: tuple[int, int] | None = None,
) -> CropRegion:
    """Compute the optimal crop rectangle for a 9:16 vertical output.

    Args:
        src_w: Source video width.
        src_h: Source video height.
        target_w: Output width (default 1080).
        target_h: Output height (default 1920).
        face_center: Optional (x, y) of detected face center in source frame.

    Returns:
        CropRegion with the computed crop parameters.
    """
    target_ratio = target_w / target_h  # 0.5625 for 9:16
    src_ratio = src_w / src_h

    # If source is already portrait or nearly square, minimal crop
    if src_ratio <= target_ratio * 1.1:
        return CropRegion(
            x=0, y=0, w=src_w, h=src_h,
            scale_w=target_w, scale_h=target_h,
            strategy=CropStrategy.PASSTHROUGH,
        )

    # Source is wider than target (typical landscape → portrait conversion).
    # Crop width to match 9:16 ratio, keeping full height.
    crop_w = int(src_h * target_ratio)
    crop_h = src_h

    # Ensure crop doesn't exceed source dimensions
    crop_w = min(crop_w, src_w)

    if face_center:
        # Center crop on the detected face horizontally
        cx, _ = face_center
        crop_x = cx - crop_w // 2
        # Clamp to frame bounds
        crop_x = max(0, min(crop_x, src_w - crop_w))
        strategy = CropStrategy.FACE_DETECT
    else:
        # Default: center crop with a slight bias toward the left third
        # (in many presentation/webinar layouts, the speaker is on the left
        # while slides are on the right)
        crop_x = (src_w - crop_w) // 2
        strategy = CropStrategy.PROBE_CENTER

    return CropRegion(
        x=crop_x,
        y=0,
        w=crop_w,
        h=crop_h,
        scale_w=target_w,
        scale_h=target_h,
        strategy=strategy,
    )


# ── Public API ────────────────────────────────────────────────────────


def smart_crop_to_vertical(
    video_path: Path,
    output_path: Path,
    target_w: int = 1080,
    target_h: int = 1920,
) -> CropRegion:
    """Crop a video to vertical 9:16 format using the best available strategy.

    1. Probes source dimensions.
    2. Attempts face detection (if OpenCV is installed).
    3. Computes an optimal crop region.
    4. Applies the crop via FFmpeg.

    Args:
        video_path: Source video file.
        output_path: Destination file.
        target_w: Output width (default 1080).
        target_h: Output height (default 1920).

    Returns:
        The CropRegion that was applied (useful for logging/debugging).
    """
    _validate_input(video_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Probe dimensions
    try:
        src_w, src_h = probe_video_dimensions(video_path)
    except Exception as exc:
        logger.warning("crop_probe_failed", error=str(exc))
        # Fallback: blind center crop (original behavior)
        run_ffmpeg([
            "-i", str(video_path),
            "-vf", f"crop=ih*9/16:ih,scale={target_w}:{target_h}",
            "-c:a", "copy",
            str(output_path),
        ])
        return CropRegion(
            x=0, y=0, w=0, h=0,
            scale_w=target_w, scale_h=target_h,
            strategy=CropStrategy.CENTER,
        )

    # Step 2: Attempt face detection
    face_center = _try_detect_face_center(video_path)

    # Step 3: Compute crop region
    region = compute_crop_region(src_w, src_h, target_w, target_h, face_center)

    logger.info(
        "crop_applied",
        strategy=region.strategy.value,
        source=f"{src_w}x{src_h}",
        crop=f"{region.w}x{region.h}+{region.x}+{region.y}",
        output=f"{region.scale_w}x{region.scale_h}",
    )

    # Step 4: Apply via FFmpeg
    run_ffmpeg([
        "-i", str(video_path),
        "-vf", region.vf_string,
        "-c:a", "copy",
        str(output_path),
    ])

    return region
