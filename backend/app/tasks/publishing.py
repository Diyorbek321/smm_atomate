"""Scheduler + publisher: the loop that actually posts approved content."""

from __future__ import annotations

import uuid
from typing import Any

from celery import shared_task

from app.bot.notifier import notify_admins
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.enums import ContentItemStatus
from app.repositories.business import BusinessRepository
from app.repositories.content import ContentItemRepository
from app.services.publisher import PublishingService
from app.tasks.celery_app import celery_app  # noqa: F401 - registers the app
from app.tasks.runner import run_async
from app.utils.dates import humanize, utcnow

log = get_logger(__name__)


@shared_task(name="app.tasks.publishing.publish_due_content")
def publish_due_content(limit: int | None = None) -> dict[str, Any]:
    """Runs every minute: publish every approved item whose time has come.

    Rows are locked with ``FOR UPDATE SKIP LOCKED`` so several workers can run
    this task concurrently without double-posting.
    """
    batch = limit or settings.publish_batch_size

    async def _run() -> dict[str, Any]:
        published = failed = 0
        async with session_scope() as session:
            items = list(await ContentItemRepository(session).due_for_publishing(limit=batch))
            if not items:
                return {"due": 0, "published": 0, "failed": 0}

            businesses = BusinessRepository(session)
            service = PublishingService(session)
            cache: dict[uuid.UUID, Any] = {}

            for item in items:
                business = cache.get(item.business_id)
                if business is None:
                    business = await businesses.get_full(item.business_id)
                    if business is None:
                        item.mark_failed("business not found")
                        failed += 1
                        continue
                    cache[item.business_id] = business

                if not business.is_active:
                    item.status = ContentItemStatus.REJECTED
                    item.last_error = "business is inactive"
                    continue

                result = await service.publish(item, business)
                if item.status == ContentItemStatus.PUBLISHED:
                    published += 1
                else:
                    failed += 1
                    if item.retry_count >= settings.max_publish_retries:
                        await notify_admins(
                            session,
                            business.id,
                            f"❌ <b>Chop etib bo'lmadi</b>\n\n{item.short_title()}\n"
                            f"🕐 {humanize(item.scheduled_at, business.timezone)}\n"
                            f"<code>{(result.errors or item.last_error or '')[:300]}</code>",
                        )
            return {"due": len(items), "published": published, "failed": failed}

    outcome = run_async(_run())
    if outcome["due"]:
        log.info("publish_cycle", **outcome)
    return outcome


@shared_task(name="app.tasks.publishing.publish_item", bind=True, max_retries=3, default_retry_delay=120)
def publish_item(self: Any, item_id: str, force: bool = False) -> dict[str, Any]:
    """Publish one specific item (manual trigger from the dashboard/bot)."""

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            item = await ContentItemRepository(session).get_or_404(uuid.UUID(item_id))
            business = await BusinessRepository(session).get_full_or_404(item.business_id)
            result = await PublishingService(session).publish(item, business, force=force)
            return {
                "item_id": item_id,
                "status": str(item.status),
                "outcomes": [
                    {"platform": o.platform.value, "state": o.state.value, "external_id": o.external_id}
                    for o in result.outcomes
                ],
                "errors": result.errors,
            }

    outcome = run_async(_run())
    if outcome["status"] == ContentItemStatus.FAILED.value:
        log.warning("manual_publish_failed", item=item_id, errors=outcome["errors"])
    return outcome


@shared_task(name="app.tasks.publishing.retry_failed")
def retry_failed(limit: int = 25) -> dict[str, Any]:
    """Re-queue transient publication failures below the retry ceiling."""

    async def _run() -> list[str]:
        async with session_scope() as session:
            items = await ContentItemRepository(session).retryable_failures(
                max_retries=settings.max_publish_retries, limit=limit
            )
            ids = []
            for item in items:
                item.status = ContentItemStatus.APPROVED  # publish_due_content picks it up again
                item.scheduled_at = min(item.scheduled_at, utcnow())
                ids.append(str(item.id))
            return ids

    retried = run_async(_run())
    if retried:
        log.info("publish_retry_queued", count=len(retried))
    return {"retried": len(retried), "item_ids": retried}
