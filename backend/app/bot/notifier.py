"""Outbound bot messaging used by Celery workers (no dispatcher involved)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from aiogram.types import FSInputFile, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.main import bot_session
from app.bot.review import send_item_for_review, send_plan_summary
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.models.business import Business, BusinessAdmin
from app.models.content_item import ContentItem
from app.models.content_plan import ContentPlan
from app.repositories.business import AdminRepository

log = get_logger(__name__)


async def reviewers_for(session: AsyncSession, business_id: uuid.UUID) -> Sequence[BusinessAdmin]:
    return await AdminRepository(session).reviewers(business_id)


async def push_items_for_review(
    session: AsyncSession, business: Business, items: Sequence[ContentItem]
) -> int:
    """Send each item to every reviewer; records the message id for later edits."""
    reviewers = await reviewers_for(session, business.id)
    if not reviewers or not items:
        return 0

    sent = 0
    try:
        async with bot_session() as bot:
            for item in items:
                for reviewer in reviewers:
                    message_id = await send_item_for_review(bot, item, business, reviewer.telegram_user_id)
                    if message_id is None:
                        continue
                    sent += 1
                    # The first successful delivery owns the editable card.
                    if not item.sent_for_review:
                        item.review_message_id = message_id
                        item.review_chat_id = reviewer.telegram_user_id
                        item.sent_for_review = True
            await session.flush()
    except ConfigurationError as exc:
        log.warning("review_push_skipped", reason=str(exc))
    return sent


async def push_plan_summary(session: AsyncSession, business: Business, plan: ContentPlan) -> int:
    reviewers = await reviewers_for(session, business.id)
    if not reviewers:
        return 0
    sent = 0
    try:
        async with bot_session() as bot:
            for reviewer in reviewers:
                if await send_plan_summary(bot, plan, business, reviewer.telegram_user_id):
                    sent += 1
    except ConfigurationError as exc:
        log.warning("plan_summary_skipped", reason=str(exc))
    return sent


async def notify_admins(session: AsyncSession, business_id: uuid.UUID, text: str) -> int:
    """Plain text broadcast (publish failures, token expiry, …)."""
    reviewers = await reviewers_for(session, business_id)
    sent = 0
    try:
        async with bot_session() as bot:
            for reviewer in reviewers:
                try:
                    await bot.send_message(reviewer.telegram_user_id, text)
                    sent += 1
                except Exception as exc:
                    log.warning("notify_failed", user=reviewer.telegram_user_id, error=str(exc)[:160])
    except ConfigurationError as exc:
        log.warning("notify_skipped", reason=str(exc))
    return sent


async def push_clip(
    session: AsyncSession,
    business_id: uuid.UUID,
    path: str,
    caption: str = "",
) -> int:
    """Send a finished clip straight to the owners.

    A rendered clip is not a :class:`ContentItem` — it has no schedule, no
    caption to approve, nothing to edit. It is a file someone asked for, so it
    goes to them as a file rather than through the review flow.
    """
    reviewers = await reviewers_for(session, business_id)
    sent = 0
    try:
        async with bot_session() as bot:
            for reviewer in reviewers:
                try:
                    await bot.send_video(
                        reviewer.telegram_user_id,
                        FSInputFile(path),
                        caption=caption or None,
                        supports_streaming=True,
                    )
                    sent += 1
                except Exception as exc:
                    log.warning("clip_push_failed", user=reviewer.telegram_user_id,
                                error=str(exc)[:160])
    except ConfigurationError as exc:
        log.warning("clip_push_skipped", reason=str(exc))
    return sent


async def push_slides(
    session: AsyncSession,
    business_id: uuid.UUID,
    paths: Sequence[str],
    caption: str = "",
) -> int:
    """Send carousel slides as one album — Telegram caps a group at ten."""
    reviewers = await reviewers_for(session, business_id)
    if not paths:
        return 0
    sent = 0
    try:
        async with bot_session() as bot:
            for reviewer in reviewers:
                try:
                    album = [
                        InputMediaPhoto(media=FSInputFile(path),
                                        caption=caption if index == 0 and caption else None)
                        for index, path in enumerate(paths[:10])
                    ]
                    await bot.send_media_group(reviewer.telegram_user_id, album)
                    sent += 1
                except Exception as exc:
                    log.warning("slides_push_failed", user=reviewer.telegram_user_id,
                                error=str(exc)[:160])
    except ConfigurationError as exc:
        log.warning("slides_push_skipped", reason=str(exc))
    return sent
