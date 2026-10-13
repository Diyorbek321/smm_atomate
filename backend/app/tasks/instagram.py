"""Answering an Instagram DM or comment, off the request path.

The webhook authenticates and queues; everything that can be slow — finding the
business, reading the knowledge base, asking a model, calling Meta back — runs
here. Failures are logged and swallowed rather than retried into a loop: Meta
already retries the delivery, and a task that also retries turns one unanswered
question into four identical replies under somebody's post.
"""

from __future__ import annotations

import re
from typing import Any

from celery import shared_task
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.business import BusinessCredentials
from app.tasks.celery_app import celery_app  # noqa: F401 - registers the app
from app.tasks.runner import run_async

log = get_logger(__name__)

#: Uzbek mobile numbers as people actually type them: +998 90 123 45 67,
#: 90 123-45-67, 901234567. Nine digits after an optional country code.
PHONE = re.compile(r"(?:\+?998[\s-]?)?(\d{2})[\s-]?(\d{3})[\s-]?(\d{2})[\s-]?(\d{2})\b")


def find_phone(text: str) -> str:
    """The first phone number in a message, normalised, or `""`.

    A DM is not a form: the number arrives inside a sentence, or not at all.
    Waiting for a dedicated "now send your phone" turn is what the Telegram
    flow does and what makes it wrong here.
    """
    match = PHONE.search(text or "")
    if not match:
        return ""
    return "+998" + "".join(match.groups())


@shared_task(name="app.tasks.instagram.handle_event", bind=True, max_retries=0)
def handle_event(
    self: Any,
    account_id: str,
    kind: str,
    sender_id: str,
    text: str,
    *,
    comment_id: str = "",
    username: str = "",
) -> dict[str, Any]:
    """Answer one inbound message or comment, and keep the contact if given."""
    from app.agents.reply import ReplyAgent
    from app.repositories.business import (
        BusinessRepository,
        KnowledgeBaseRepository,
    )
    from app.repositories.lead import LeadRepository
    from app.services.instagram_messaging import InstagramMessenger

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            # One webhook serves every client, so the account id is the only
            # thing that says whose inbox this is.
            stmt = select(BusinessCredentials).where(
                BusinessCredentials.ig_account_id == account_id
            )
            credentials = (await session.execute(stmt)).scalars().one_or_none()
            if credentials is None:
                log.warning("ig_event_unknown_account", account=account_id)
                return {"handled": False, "reason": "unknown_account"}
            if not credentials.instagram_ready:
                return {"handled": False, "reason": "instagram_off"}

            business = await BusinessRepository(session).get(credentials.business_id)
            if business is None or not business.is_active:
                return {"handled": False, "reason": "inactive"}
            if not business.capabilities.lead_autoreply:
                log.info("ig_autoreply_skipped_plan", plan=str(business.plan))
                return {"handled": False, "reason": "plan"}

            knowledge = await KnowledgeBaseRepository(session).for_business(business.id)
            answer = await ReplyAgent(session=session).answer(
                business, knowledge, text, public=(kind == "comment")
            )

            phone = find_phone(text)
            lead = None
            # A DM is already an intent worth keeping even without a number; a
            # public comment is not, until they hand one over.
            if phone or kind == "message":
                lead = await LeadRepository(session).add(
                    business_id=business.id,
                    telegram_user_id=None,
                    ig_user_id=sender_id,
                    username=(f"@{username}" if username else ""),
                    phone=phone,
                    interest=text[:2000],
                    source=f"instagram_{kind}",
                )
            token, ig_id = credentials.ig_access_token, credentials.ig_account_id
            business_id, lead_id = business.id, (lead.id if lead else None)

        if phone:
            # After the commit above, so the CRM task can see the row.
            from app.tasks.crm import enqueue_sync

            enqueue_sync(lead_id)

        if not answer:
            log.info("ig_no_answer", kind=kind, account=account_id)
            return {"handled": False, "reason": "no_answer", "lead": str(lead_id or "")}

        messenger = InstagramMessenger(token=token or "", account_id=ig_id or "")
        try:
            if kind == "comment" and comment_id:
                await messenger.reply_to_comment(comment_id, answer)
                # The single private reply a comment earns carries the answer,
                # so somebody who scrolls past the thread still has it.
                await messenger.private_reply(comment_id, answer)
            else:
                await messenger.send_dm(sender_id, answer)
        except Exception as exc:
            log.warning("ig_reply_failed", kind=kind, error=str(exc)[:250])
            return {"handled": False, "reason": "send_failed"}

        if lead_id is not None and phone:
            async with session_scope() as session:
                from app.bot.notifier import notify_admins

                who = f"@{username}" if username else "noma'lum"
                await notify_admins(
                    session, business_id,
                    f"📩 Instagramdan yangi kontakt\n{who} · {phone}\n"
                    f"Savol: {text[:200]}",
                )
        log.info("ig_answered", kind=kind, account=account_id, phone=bool(phone))
        return {"handled": True, "kind": kind, "lead": str(lead_id or ""),
                "phone": bool(phone)}

    try:
        return run_async(_run())
    except Exception as exc:
        # Meta retries the delivery itself; retrying here as well is how one
        # question becomes four identical public replies.
        log.warning("ig_event_failed", account=account_id, error=str(exc)[:250])
        return {"handled": False, "reason": "error"}
