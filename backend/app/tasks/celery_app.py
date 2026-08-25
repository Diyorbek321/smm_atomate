"""Celery application, queues and beat schedule."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.logging import configure_logging

configure_logging("worker")

celery_app = Celery(
    "autosmm",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.generation",
        "app.tasks.publishing",
        "app.tasks.maintenance",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.default_timezone,
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,          # recycle workers: Chromium leaks
    result_expires=3600 * 24,
    broker_connection_retry_on_startup=True,
    task_default_queue="default",
    task_routes={
        "app.tasks.generation.*": {"queue": "generation"},
        "app.tasks.publishing.*": {"queue": "publishing"},
        "app.tasks.maintenance.*": {"queue": "default"},
    },
    task_annotations={
        "app.tasks.generation.generate_weekly_plan": {"time_limit": 1800, "soft_time_limit": 1740},
        "app.tasks.generation.generate_single_item": {"time_limit": 600, "soft_time_limit": 570},
        "app.tasks.generation.regenerate_item": {"time_limit": 600, "soft_time_limit": 570},
    },
)

celery_app.conf.beat_schedule = {
    # The publishing heartbeat — the core of the scheduler.
    "publish-due-content": {
        "task": "app.tasks.publishing.publish_due_content",
        "schedule": 60.0,
        "options": {"queue": "publishing", "expires": 55},
    },
    # Retry transient publishing failures.
    "retry-failed-publications": {
        "task": "app.tasks.publishing.retry_failed",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": "publishing"},
    },
    # Deliver anything still waiting for human review.
    "send-pending-reviews": {
        "task": "app.tasks.generation.send_pending_reviews",
        "schedule": crontab(minute="*/10"),
        "options": {"queue": "generation"},
    },
    # Weekly planning run: Saturday 10:00 local time, for the coming week.
    "weekly-plans": {
        "task": "app.tasks.generation.generate_plans_for_all",
        "schedule": crontab(day_of_week="sat", hour=10, minute=0),
        "options": {"queue": "generation"},
    },
    # The 1st, in this order: what last month produced, then what this month
    # needs. Reversed, the footage request reads as a chore instead of an
    # investment.
    "monthly-client-report": {
        "task": "app.tasks.generation.send_monthly_reports",
        "schedule": crontab(day_of_month="1", hour=9, minute=0),
        "options": {"queue": "generation"},
    },
    "monthly-shooting-brief": {
        "task": "app.tasks.generation.send_shooting_briefs",
        "schedule": crontab(day_of_month="1", hour=9, minute=10),
        "options": {"queue": "generation"},
    },
    # Housekeeping.
    "cleanup-media": {
        "task": "app.tasks.maintenance.cleanup_media",
        "schedule": crontab(hour=3, minute=30),
    },
    # A client's knowledge base and content queue exist nowhere else.
    "backup-database": {
        "task": "app.tasks.maintenance.backup_database",
        "schedule": crontab(hour=3, minute=0),
    },
    "unstick-stale-items": {
        "task": "app.tasks.maintenance.unstick_stale_items",
        "schedule": crontab(minute="*/30"),
    },
}

__all__ = ["celery_app"]
