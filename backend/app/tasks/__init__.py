"""Celery tasks. Import `celery_app` from here in worker entrypoints."""

from app.tasks.celery_app import celery_app

__all__ = ["celery_app"]
