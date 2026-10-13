"""Channel comments heard by the platform bot.

The platform bot already publishes to every client's channel, so it can sit in
each linked discussion group and answer comments there — no second bot, no
webhook. The answer itself is :mod:`app.tasks.telegram_chat`, the same task a
business's own bot feeds.

This router comes first and takes *every* group message: the catch-all in
:mod:`app.bot.handlers.voice` was written for DMs, and a group chatter must
never be greeted as a lead or ingested as an admin's note.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.business import BusinessCredentials
from app.services.telegram_chat import match_business, message_to_update, parse_update

log = get_logger(__name__)
router = Router(name="comments")


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def channel_comment(message: Message, session: AsyncSession) -> None:
    event = parse_update(message_to_update(message))
    if event is None or event.kind != "comment":
        return

    stmt = select(
        BusinessCredentials.business_id,
        BusinessCredentials.tg_channel_id,
        BusinessCredentials.tg_discussion_chat_id,
    ).where(BusinessCredentials.telegram_enabled.is_(True))
    business_id = match_business(event, (await session.execute(stmt)).all())
    if business_id is None:
        log.info("tg_comment_foreign_group", chat=event.chat_id, channel=event.channel_username)
        return

    from app.tasks.dispatch import enqueue

    if not enqueue("app.tasks.telegram_chat.handle_update", str(business_id), event.to_task()):
        log.error("tg_comment_no_queue", business=str(business_id))
