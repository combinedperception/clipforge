#!/usr/bin/env python3
"""Smoke-test the ClipForge AI pipeline end-to-end.

Usage:
    python scripts/smoke_test_pipeline.py --input test_files/video.mp4

This script bypasses the API and Celery layer to test the core pipeline
directly: ingest → extract audio → transcribe → agent pipeline → render.
It prints a summary and exits 0 on success or 1 on failure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Add backend to path so we can import app modules
_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))


def _print(label: str, msg: str, ok: bool = True) -> None:
    symbol = "✓" if ok else "✗"
    print(f"  [{symbol}] {label}: {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the ClipForge pipeline.")
    parser.add_argument("--input", required=True, help="Path to input video file.")
    parser.add_argument("--keep", action="store_true", help="Keep output directory after test.")
    parser.add_argument("--mock-transcribe", action="store_true",
                        help="Use mock transcription (no API key needed).")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        print(f"ERROR: Input file not found: {input_path}")
        return 1

    print(f"\n=== ClipForge Pipeline Smoke Test ===")
    print(f"Input: {input_path} ({input_path.stat().st_size / 1024 / 1024:.1f} MB)\n")

    # Create a temporary working directory
    work_dir = Path(tempfile.mkdtemp(prefix="clipforge_smoke_"))
    print(f"Work directory: {work_dir}")

    errors: list[str] = []
    t_total = time.monotonic()

    try:
        # ── Step 1: Validate input ────────────────────────
        print("\n[1/6] Validating input video...")
        from app.video_pipeline.ingest import validate_video_file
        try:
            validate_video_file(
                filename=input_path.name,
                content_type=None,
                size_bytes=input_path.stat().st_size,
                max_size_bytes=500 * 1024 * 1024,
            )
            _print("Validation", "passed")
        except Exception as e:
            _print("Validation", str(e), ok=False)
            errors.append(f"Validation: {e}")
            return 1

        # ── Step 2: FFmpeg probe ──────────────────────────
        print("\n[2/6] Probing video with FFmpeg...")
        from app.video_pipeline.audio import check_ffmpeg_available
        if not check_ffmpeg_available():
            _print("FFmpeg", "not found on PATH", ok=False)
            errors.append("FFmpeg not available")
            return 1
        _print("FFmpeg", "available")

        import subprocess
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size:stream=codec_type,codec_name,width,height",
             "-of", "json", str(input_path)],
            capture_output=True, text=True,
        )
        if probe.returncode != 0:
            _print("Probe", f"ffprobe failed: {probe.stderr.strip()}", ok=False)
            errors.append("ffprobe failed")
            return 1

        probe_data = json.loads(probe.stdout)
        duration = float(probe_data.get("format", {}).get("duration", 0))
        _print("Probe", f"duration={duration:.1f}s, streams={len(probe_data.get('streams', []))}")

        # ── Step 3: Extract audio ─────────────────────────
        print("\n[3/6] Extracting audio...")
        from app.video_pipeline.audio import extract_audio
        t = time.monotonic()
        audio_path = work_dir / "audio.wav"
        extract_audio(input_path, audio_path)
        if not audio_path.exists() or audio_path.stat().st_size == 0:
            _print("Audio", "extraction produced empty file", ok=False)
            errors.append("Empty audio file")
            return 1
        _print("Audio", f"{audio_path.stat().st_size / 1024 / 1024:.1f} MB ({time.monotonic()-t:.1f}s)")

        # ── Step 4: Transcribe ────────────────────────────
        print("\n[4/6] Transcribing audio...")
        import asyncio
        from app.video_pipeline.transcribe import get_transcription_service
        from app.core.config import get_settings

        settings = get_settings()
        api_key = "" if args.mock_transcribe else settings.openai_api_key
        service = get_transcription_service(api_key=api_key)
        provider = "mock" if not api_key else "openai"

        t = time.monotonic()
        transcript = asyncio.run(service.transcribe(audio_path))
        transcript.video_id = "smoke_test"
        _print("Transcribe", f"{len(transcript.segments)} segments, "
               f"{transcript.word_count} words, provider={provider} ({time.monotonic()-t:.1f}s)")

        if not transcript.segments:
            _print("Transcribe", "no segments produced", ok=False)
            errors.append("Empty transcript")
            return 1

        # Save transcript
        (work_dir / "transcript.json").write_text(transcript.model_dump_json(indent=2))

        # ── Step 5: Agent pipeline ────────────────────────
        print("\n[5/6] Running agent pipeline (segment → score → select → edit plans → metadata → QA)...")
        from app.agents.graph import run_pipeline
        t = time.monotonic()
        result = run_pipeline(
            video_id="smoke_test",
            transcript=transcript,
        )
        edit_plans = result.get("edit_plans", [])
        qa_results = result.get("qa_results", [])
        pipeline_errors = result.get("errors", [])

        if pipeline_errors:
            for e in pipeline_errors:
                _print("Pipeline", e, ok=False)
            errors.extend(pipeline_errors)
            return 1

        _print("Pipeline", f"{len(edit_plans)} edit plans generated ({time.monotonic()-t:.1f}s)")

        if qa_results:
            passed = sum(1 for r in qa_results if r.get("passed"))
            _print("QA", f"{passed}/{len(qa_results)} passed")

        if not edit_plans:
            _print("Pipeline", "no edit plans generated", ok=False)
            errors.append("No edit plans")
            return 1

        # Save edit plans
        (work_dir / "edit_plans.json").write_text(
            json.dumps([p.model_dump() for p in edit_plans], indent=2, default=str)
        )

        # ── Step 6: Render clips ──────────────────────────
        print(f"\n[6/6] Rendering {len(edit_plans)} clips...")
        from app.video_pipeline.captions import generate_srt
        from app.video_pipeline.render import render_clip_from_edit_plan

        clips_dir = work_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        rendered = []

        for i, plan in enumerate(edit_plans, 1):
            t = time.monotonic()
            # Generate SRT
            clip_segments = [
                seg for seg in transcript.segments
                if seg.start_time >= plan.start_time and seg.end_time <= plan.end_time
            ]
            srt_path = clips_dir / f"{plan.clip_id}.srt"
            if clip_segments:
                generate_srt(clip_segments, srt_path, offset=plan.start_time)

            # Render
            output = render_clip_from_edit_plan(
                plan, input_path, clips_dir,
                srt_path=srt_path if srt_path.exists() else None,
            )
            if output.exists() and output.stat().st_size > 0:
                rendered.append(output)
                _print(f"Clip {i}/{len(edit_plans)}",
                       f"{plan.clip_id} — {plan.duration:.1f}s, "
                       f"{output.stat().st_size / 1024:.0f} KB ({time.monotonic()-t:.1f}s)")
            else:
                _print(f"Clip {i}", f"{plan.clip_id} — render failed", ok=False)
                errors.append(f"Render failed: {plan.clip_id}")

        # ── Summary ──────────────────────────────────────
        elapsed = time.monotonic() - t_total
        print(f"\n{'='*48}")
        print(f"  Clips rendered: {len(rendered)}/{len(edit_plans)}")
        print(f"  Output directory: {work_dir}")
        print(f"  Total time: {elapsed:.1f}s")

        if errors:
            print(f"\n  ERRORS ({len(errors)}):")
            for e in errors:
                print(f"    - {e}")
            print(f"\n  RESULT: FAIL")
            return 1
        else:
            print(f"\n  RESULT: PASS ✓")
            return 0

    finally:
        if not args.keep and not errors:
            shutil.rmtree(work_dir, ignore_errors=True)
            print(f"\n  (Cleaned up {work_dir})")
        elif not args.keep and errors:
            print(f"\n  (Kept {work_dir} for inspection due to errors)")


if __name__ == "__main__":
    sys.exit(main())
