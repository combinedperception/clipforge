"""Quality assurance checks for rendered clips."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.core.logging import get_logger
from app.schemas.clip import EditPlan

logger = get_logger(__name__)


class QAResult:
    """Result of a quality assurance check."""

    def __init__(self) -> None:
        self.passed: bool = True
        self.issues: list[str] = []

    def fail(self, issue: str) -> None:
        self.passed = False
        self.issues.append(issue)

    def warn(self, issue: str) -> None:
        self.issues.append(f"[WARN] {issue}")


def run_qa_checks(
    edit_plan: EditPlan,
    rendered_path: Path | None,
    srt_path: Path | None = None,
) -> QAResult:
    """Run quality assurance checks on a rendered clip.

    Checks:
    - Duration is within acceptable range
    - Timestamps are valid
    - Output file exists and has non-zero size
    - Caption file exists (if expected)
    """
    result = QAResult()

    # Check timestamps
    if edit_plan.start_time >= edit_plan.end_time:
        result.fail(f"Invalid timestamps: start ({edit_plan.start_time}) >= end ({edit_plan.end_time})")

    if edit_plan.start_time < 0:
        result.fail(f"Negative start time: {edit_plan.start_time}")

    # Check duration
    duration = edit_plan.duration
    if duration < 5:
        result.fail(f"Clip too short: {duration:.1f}s (minimum 5s)")
    elif duration > 180:
        result.fail(f"Clip too long: {duration:.1f}s (maximum 180s)")
    elif duration < 15:
        result.warn(f"Clip is quite short: {duration:.1f}s")

    # Check rendered file
    if rendered_path is None:
        result.fail("No rendered file path provided")
    elif not rendered_path.exists():
        result.fail(f"Rendered file does not exist: {rendered_path}")
    elif rendered_path.stat().st_size == 0:
        result.fail(f"Rendered file is empty: {rendered_path}")
    else:
        # Verify audio + video streams via ffprobe
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_streams", "-of", "json",
                    str(rendered_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if probe.returncode == 0:
                data = json.loads(probe.stdout)
                codec_types = {s.get("codec_type") for s in data.get("streams", [])}
                if "video" not in codec_types:
                    result.fail("Rendered file is missing a video stream")
                if "audio" not in codec_types:
                    result.fail("Rendered file is missing an audio stream")
            else:
                result.warn("Could not probe rendered file streams")
        except Exception as exc:
            result.warn(f"ffprobe check failed: {exc}")

    # Check captions
    if srt_path is not None and not srt_path.exists():
        result.warn(f"SRT file not found: {srt_path}")

    # Check metadata
    if not edit_plan.metadata.title:
        result.warn("Missing title in metadata")
    if not edit_plan.metadata.description:
        result.warn("Missing description in metadata")

    if result.passed:
        logger.info("qa_passed", clip_id=edit_plan.clip_id, issues=result.issues)
    else:
        logger.warning("qa_failed", clip_id=edit_plan.clip_id, issues=result.issues)

    return result
