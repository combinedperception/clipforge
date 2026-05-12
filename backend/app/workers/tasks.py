"""Celery task definitions for video processing pipeline."""

from __future__ import annotations

import json
import time
import traceback
from functools import lru_cache
from pathlib import Path

from app.agents.graph import run_pipeline
from app.core.config import get_settings
from app.core.logging import get_logger
from app.video_pipeline.audio import extract_audio
from app.video_pipeline.captions import generate_srt, generate_srt_from_words
from app.video_pipeline.render import render_clip_from_edit_plan
from app.video_pipeline.transcribe import get_transcription_service
from app.workers.celery_app import celery_app

logger = get_logger(__name__)
settings = get_settings()


@lru_cache
def _sync_engine():
    """Create a single cached synchronous engine for Celery workers."""
    from sqlalchemy import create_engine

    db_url = settings.database_url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")
    return create_engine(db_url, pool_pre_ping=True)


def _update_job_status(
    job_id: str,
    status: str,
    message: str = "",
    error: str | None = None,
) -> None:
    """Synchronously update job status in the database."""
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    from app.db.models import VideoJob

    logger.info("status_update", job_id=job_id, status=status, message=message)

    with Session(_sync_engine()) as session:
        stmt = (
            update(VideoJob)
            .where(VideoJob.id == job_id)
            .values(status=status, current_stage_message=message)
        )
        if error is not None:
            stmt = stmt.values(error_message=error)
        result = session.execute(stmt)
        session.commit()

        if result.rowcount == 0:
            logger.error(
                "status_update_no_rows",
                job_id=job_id,
                status=status,
                hint="Job row may not exist yet — was the DB commit done before task dispatch?",
            )


@celery_app.task(
    bind=True,
    name="process_video_job",
    max_retries=2,
    autoretry_for=(IOError, ConnectionError),
    retry_backoff=30,
)
def process_video_job(self, job_id: str) -> dict:
    """Main pipeline task: process a video from upload through clip generation.

    Steps:
    1. Extract audio from source video
    2. Transcribe audio
    3. Run agent pipeline (segment → select → edit plans → metadata → QA)
    4. Render clips via FFmpeg
    5. Generate and burn captions

    Args:
        job_id: The VideoJob ID to process.

    Returns:
        Summary dict with clip count and status.
    """
    logger.info("task_start", job_id=job_id, task_id=self.request.id)
    t_pipeline = time.monotonic()

    try:
        # Resolve paths
        job_dir = Path(settings.local_storage_path) / "jobs" / job_id
        source_video = job_dir / "source.mp4"

        if not source_video.exists():
            raise FileNotFoundError(f"Source video not found: {source_video}")

        # ── Step 1: Extract audio ─────────────────────────
        _update_job_status(job_id, "extracting_audio", "Extracting audio track...")
        t_step = time.monotonic()
        audio_path = job_dir / "audio.wav"
        extract_audio(source_video, audio_path)
        logger.info("step_done", job_id=job_id, step="extract_audio", elapsed=f"{time.monotonic()-t_step:.1f}s")

        # ── Step 2: Transcribe ────────────────────────────
        _update_job_status(job_id, "transcribing", "Transcribing audio to text...")
        t_step = time.monotonic()
        service = get_transcription_service(api_key=settings.openai_api_key)

        import asyncio

        transcript = asyncio.run(service.transcribe(audio_path))
        transcript.video_id = job_id
        logger.info(
            "step_done", job_id=job_id, step="transcribe",
            segments=len(transcript.segments), elapsed=f"{time.monotonic()-t_step:.1f}s",
        )

        # Save transcript
        transcript_path = job_dir / "transcript.json"
        transcript_path.write_text(transcript.model_dump_json(indent=2))

        # ── Step 3: Run agent pipeline ────────────────────
        _update_job_status(job_id, "segmenting", "Identifying key moments...")
        t_step = time.monotonic()
        result = run_pipeline(
            video_id=job_id,
            transcript=transcript,
        )
        logger.info(
            "step_done", job_id=job_id, step="agent_pipeline",
            edit_plans=len(result.get("edit_plans", [])),
            errors=result.get("errors", []),
            elapsed=f"{time.monotonic()-t_step:.1f}s",
        )

        edit_plans = result.get("edit_plans", [])
        if not edit_plans:
            _update_job_status(
                job_id, "failed",
                error="No edit plans generated. The video may be too short or the transcript too sparse.",
            )
            return {"job_id": job_id, "status": "failed", "reason": "no_edit_plans"}

        # Save edit plans
        _update_job_status(job_id, "generating_edit_plans", f"Generated {len(edit_plans)} edit plans")
        plans_path = job_dir / "edit_plans.json"
        plans_path.write_text(
            json.dumps([p.model_dump() for p in edit_plans], indent=2, default=str)
        )

        # ── Step 4: Render clips ──────────────────────────
        output_dir = job_dir / "clips"
        output_dir.mkdir(parents=True, exist_ok=True)

        rendered_clips = []
        for i, plan in enumerate(edit_plans, 1):
            _update_job_status(
                job_id, "rendering",
                f"Rendering clip {i} of {len(edit_plans)}...",
            )
            t_step = time.monotonic()

            # Generate SRT for this clip — use overlapping segments, not strict containment
            clip_segments = [
                seg for seg in transcript.segments
                if seg.end_time > plan.start_time and seg.start_time < plan.end_time
            ]
            srt_path = output_dir / f"{plan.clip_id}.srt"
            if clip_segments:
                # Prefer word-level SRT for modern short-form caption style
                generate_srt_from_words(clip_segments, srt_path, offset=plan.start_time)

            # Render
            rendered = render_clip_from_edit_plan(
                plan, source_video, output_dir,
                srt_path=srt_path if srt_path.exists() else None,
            )
            rendered_clips.append({
                "clip_id": plan.clip_id,
                "path": str(rendered),
                "edit_plan": plan.model_dump(),
            })
            logger.info(
                "clip_rendered", job_id=job_id,
                clip=i, total=len(edit_plans),
                elapsed=f"{time.monotonic()-t_step:.1f}s",
            )

        # ── Step 5: Save clip records ─────────────────────
        _update_job_status(job_id, "generating_metadata", "Saving clip metadata...")
        _save_clip_records(job_id, rendered_clips)

        # ── Done ──────────────────────────────────────────
        elapsed_total = time.monotonic() - t_pipeline
        _update_job_status(
            job_id, "ready_for_review",
            f"{len(rendered_clips)} clips ready for review (processed in {elapsed_total:.0f}s)",
        )
        logger.info(
            "task_complete", job_id=job_id,
            clip_count=len(rendered_clips),
            elapsed_total=f"{elapsed_total:.1f}s",
        )

        return {
            "job_id": job_id,
            "status": "ready_for_review",
            "clip_count": len(rendered_clips),
        }

    except Exception as exc:
        logger.exception("task_failed", job_id=job_id, error=str(exc))
        _update_job_status(job_id, "failed", error=traceback.format_exc()[:2000])
        raise


def _save_clip_records(job_id: str, rendered_clips: list[dict]) -> None:
    """Save rendered clip records to the database."""
    from sqlalchemy.orm import Session

    from app.db.models import CandidateClip

    with Session(_sync_engine()) as session:
        for i, clip_data in enumerate(rendered_clips):
            plan = clip_data["edit_plan"]
            clip = CandidateClip(
                job_id=job_id,
                clip_index=i,
                edit_plan=plan,
                transcript_snippet=plan.get("hook", ""),
                rendered_path=clip_data["path"],
                start_time=plan.get("start_time", 0),
                end_time=plan.get("end_time", 0),
                score_overall=plan.get("score", {}).get("overall", 0),
            )
            session.add(clip)
        session.commit()
    logger.info("clips_saved", job_id=job_id, count=len(rendered_clips))


@celery_app.task(bind=True, name="regenerate_clip_metadata")
def regenerate_clip_metadata(self, clip_id: str) -> dict:
    """Re-generate metadata for a single clip."""
    logger.info("regenerate_metadata_start", clip_id=clip_id)
    # Placeholder – will call metadata agent for single clip
    return {"clip_id": clip_id, "status": "metadata_regenerated"}


@celery_app.task(bind=True, name="rerender_clip")
def rerender_clip(self, clip_id: str) -> dict:
    """Re-render a single clip from its existing edit plan."""
    from sqlalchemy.orm import Session

    from app.db.models import CandidateClip
    from app.schemas.clip import EditPlan

    logger.info("rerender_start", clip_id=clip_id)

    with Session(_sync_engine()) as session:
        clip = session.get(CandidateClip, clip_id)
        if clip is None:
            logger.error("rerender_clip_not_found", clip_id=clip_id)
            return {"clip_id": clip_id, "status": "failed", "reason": "clip_not_found"}

        # Reconstruct EditPlan from stored JSON
        plan = EditPlan(**clip.edit_plan)

        # Build source path the same way as the main pipeline
        job_dir = Path(settings.local_storage_path) / "jobs" / clip.job_id
        source_video = job_dir / "source.mp4"

        if not source_video.exists():
            logger.error("rerender_source_missing", clip_id=clip_id, path=str(source_video))
            return {"clip_id": clip_id, "status": "failed", "reason": "source_missing"}

        output_dir = job_dir / "clips"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load transcript for SRT generation
        transcript_path = job_dir / "transcript.json"
        srt_path = output_dir / f"{plan.clip_id}.srt"

        if transcript_path.exists():
            from app.schemas.transcript import Transcript

            transcript = Transcript(**json.loads(transcript_path.read_text()))
            clip_segments = [
                seg for seg in transcript.segments
                if seg.end_time > plan.start_time and seg.start_time < plan.end_time
            ]
            if clip_segments:
                generate_srt_from_words(clip_segments, srt_path, offset=plan.start_time)

        t_start = time.monotonic()
        rendered = render_clip_from_edit_plan(
            plan, source_video, output_dir,
            srt_path=srt_path if srt_path.exists() else None,
        )

        # Update DB record
        clip.rendered_path = str(rendered)
        session.commit()

        elapsed = time.monotonic() - t_start
        logger.info("rerender_complete", clip_id=clip_id, elapsed=f"{elapsed:.1f}s", path=str(rendered))

    return {"clip_id": clip_id, "status": "rerendered"}
