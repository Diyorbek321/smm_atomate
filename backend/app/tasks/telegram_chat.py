"""Answering a DM or a channel comment sent to a business's own Telegram bot.

The webhook authenticates and queues; finding the business, reading the
knowledge base, asking a model and replying run here. Failures are logged and
swallowed, not retried: a retry here on top of Telegram's own redelivery is how
one question gets two answers.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from celery import shared_task
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.business import BusinessCredentials
from app.tasks.celery_app import celery_app  # noqa: F401 - registers the app
from app.tasks.instagram import find_phone
from app.tasks.runner import run_async

log = get_logger(__name__)

#: What a stranger sees after /start. Short: the bot's job is to answer, and a
#: menu of options is the form this replaced.
WELCOME = (
    "Assalomu alaykum! {business} yordamchisiman.\n"
    "Savolingizni yozing — narx, jadval, kurslar haqida javob beraman."
)
#: When the knowledge base cannot answer, a human will — say so instead of
#: leaving the person on read.
HANDOFF = (
    "Savolingizni operatorga uzatdim, tez orada javob berishadi. "
    "Telefon raqamingizni qoldirsangiz, qo'ng'iroq qilamiz."
)


THANKS = "Rahmat! Raqamingizni oldim, operatorimiz tez orada qo'ng'iroq qiladi."


@shared_task(name="app.tasks.telegram_chat.handle_update", bind=True, max_retries=0)
def handle_update(self: Any, business_id: str, event: dict[str, Any]) -> dict[str, Any]:
    try:
        return run_async(_handle(uuid.UUID(business_id), event))
    except Exception as exc:
        log.warning("tg_chat_failed", business=business_id, error=str(exc)[:250])
        return {"handled": False, "reason": "error"}


async def _handle(business_id: uuid.UUID, raw: dict[str, Any]) -> dict[str, Any]:
    from app.agents.reply import ReplyAgent
    from app.repositories.business import (
        AdminRepository,
        BusinessRepository,
        KnowledgeBaseRepository,
    )
    from app.repositories.lead import LeadRepository
    from app.services.telegram_chat import ChatEvent, belongs_to_channel, send_reply

    event = ChatEvent(**raw)
    async with session_scope() as session:
        stmt = select(BusinessCredentials).where(BusinessCredentials.business_id == business_id)
        credentials = (await session.execute(stmt)).scalars().one_or_none()
        # No token of its own: the platform bot heard the comment and answers it.
        token = (credentials.tg_bot_token if credentials else None) or settings.telegram_bot_token
        if credentials is None or not credentials.telegram_enabled or not token:
            return {"handled": False, "reason": "telegram_off"}
        if not belongs_to_channel(
            event, channel_ref=credentials.tg_channel_id,
            discussion_id=credentials.tg_discussion_chat_id,
        ):
            log.info("tg_chat_foreign_group", business=str(business_id), chat=event.chat_id)
            return {"handled": False, "reason": "foreign_chat"}

        business = await BusinessRepository(session).get(business_id)
        if business is None or not business.is_active:
            return {"handled": False, "reason": "inactive"}
        if not business.capabilities.lead_autoreply:
            log.info("tg_chat_skipped_plan", plan=str(business.plan))
            return {"handled": False, "reason": "plan"}

        # The owner answering in their own comments is not a lead.
        admins = await AdminRepository(session).by_telegram_user(event.user_id)
        if any(a.business_id == business_id for a in admins) and event.kind == "comment":
            return {"handled": False, "reason": "admin"}

        leads = LeadRepository(session)
        existing = await leads.latest_from_telegram(business_id, event.user_id)
        name = business.name
        phone = find_phone(event.text) if event.kind != "start" else ""
        if event.kind == "start":
            answer = WELCOME.format(business=name)
        elif phone and len(re.sub(r"[\d\s+()-]", "", event.text)) < 4:
            # Just the number, in reply to being asked for it.
            answer = THANKS
        else:
            knowledge = await KnowledgeBaseRepository(session).for_business(business.id)
            answer = await ReplyAgent(session=session).answer(
                business, knowledge, event.text,
                public=(event.kind == "comment"), channel="Telegram",
                # A chat asks for the number once; repeating it is what makes
                # a helper read as a funnel.
                ask_phone=existing is None,
            )

        lead_id = None
        # A chat is many messages but one person: the number, when it comes,
        # completes the lead the first message opened.
        if existing is not None and (phone or event.kind == "message"):
            if phone and not existing.phone:
                existing.phone = phone
            lead_id = existing.id
        # A DM is intent worth keeping; a public comment only once it carries a number.
        elif phone or event.kind == "message":
            lead = await leads.add(
                business_id=business_id,
                telegram_user_id=event.user_id,
                full_name=event.full_name,
                username=f"@{event.username}" if event.username else "",
                phone=phone,
                interest=event.text,
                source=f"telegram_{event.kind}",
            )
            lead_id = lead.id

    if phone:
        # After the commit above, so the CRM task can see the row.
        from app.tasks.crm import enqueue_sync

        enqueue_sync(lead_id)

    if not answer and event.kind == "message":
        answer = HANDOFF
    if answer:
        try:
            await send_reply(token, event, answer)
        except Exception as exc:
            log.warning("tg_chat_send_failed", kind=event.kind, error=str(exc)[:250])
            return {"handled": False, "reason": "send_failed"}

    if phone or (event.kind == "message" and answer == HANDOFF):
        async with session_scope() as session:
            from app.bot.notifier import notify_admins

            who = f"@{event.username}" if event.username else (event.full_name or "noma'lum")
            await notify_admins(
                session, business_id,
                f"💬 Telegram chatbotdan {'kontakt' if phone else 'javobsiz savol'}\n"
                f"{who}{' · ' + phone if phone else ''}\nSavol: {event.text[:200]}",
            )
    log.info("tg_chat_answered", kind=event.kind, business=str(business_id), phone=bool(phone))
    return {"handled": bool(answer), "kind": event.kind, "lead": str(lead_id or ""),
            "phone": bool(phone)}
