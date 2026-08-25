"""Reaction counts on published channel posts — the only feedback loop we have.

Telegram's Bot API does not expose view counts; that lives in the client API.
What it does give is :class:`MessageReactionCountUpdated` — an anonymous total
per message, pushed whenever it changes, as long as the bot is an administrator
of the channel.

That is enough to answer the question the strategist could never ask before:
which of the four pillars is anyone actually responding to.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import MessageReactionCountUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.repositories.business import CredentialsRepository
from app.repositories.content import ContentItemRepository
from app.utils.dates import utcnow

router = Router(name="reactions")
log = get_logger(__name__)


@router.message_reaction_count()
async def record_reactions(
    event: MessageReactionCountUpdated, session: AsyncSession
) -> None:
    """Store the running reaction total against the item that was posted.

    Fires on every change, so this overwrites rather than accumulates — the
    event carries the current totals, not a delta.
    """
    message_id = str(event.message_id)
    # Scoped to the channel the event came from: a message id repeats across
    # channels, so an unscoped lookup eventually records one client's
    # reactions against another client's post.
    business_id = await CredentialsRepository(session).business_for_channel(
        chat_id=event.chat.id, username=getattr(event.chat, "username", None)
    )
    item = await ContentItemRepository(session).by_telegram_message(
        message_id, business_id=business_id
    )
    if item is None:
        # Anything the channel posted by hand, or from before this shipped.
        log.debug("reaction_unmatched", message_id=message_id, chat=event.chat.id)
        return

    breakdown = {
        str(getattr(count.type, "emoji", None) or getattr(count.type, "type", "?")): count.total_count
        for count in (event.reactions or [])
    }
    total = sum(breakdown.values())
    item.metrics = {
        **(item.metrics or {}),
        "reactions": total,
        "reaction_breakdown": breakdown,
        "measured_at": utcnow().isoformat(),
    }
    await session.flush()
    log.info("reactions_recorded", item=str(item.id), total=total)
