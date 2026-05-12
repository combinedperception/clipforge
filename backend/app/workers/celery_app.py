"""Celery application configuration."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "clipforge",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,  # 24 hours
    task_soft_time_limit=1800,  # 30 minutes
    task_time_limit=3600,  # 1 hour hard limit
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.workers"])


@celery_app.on_after_finalize.connect
def _log_registered_tasks(sender, **kwargs):  # noqa: ARG001
    """Log which tasks the worker discovered so startup issues are visible."""
    import logging

    app_tasks = sorted(t for t in sender.tasks if not t.startswith("celery."))
    logging.getLogger("celery.worker").info(
        "Registered %d app task(s): %s", len(app_tasks), app_tasks
    )
