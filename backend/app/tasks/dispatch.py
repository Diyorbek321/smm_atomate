"""Hand work to the Celery workers, with a clear signal when they are absent.

Both the REST API and the Telegram bot need this: generation takes minutes and
must never block the caller, but a single-process deployment (no broker) should
still work.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


def enqueue(task_name: str, *args: Any, **kwargs: Any) -> str | None:
    """Queue a task and return its id, or None when the broker is unreachable."""
    try:
        from app.tasks.celery_app import celery_app

        result = celery_app.send_task(task_name, args=list(args), kwargs=kwargs)
        log.info("task_enqueued", task=task_name, task_id=str(result.id))
        return str(result.id)
    except Exception as exc:
        log.warning("task_enqueue_failed", task=task_name, error=str(exc)[:200])
        return None
