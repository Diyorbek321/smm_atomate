"""Catch-all handler for free-form text/voice/documents outside an explicit flow.

Anything the owner says here is treated as new knowledge for the business —
that is how the knowledge base keeps growing without a formal interview.
"""

from __future__ import annotations

import contextlib
import io

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.onboarding import MAX_DOCUMENT_BYTES, OnboardingAgent
from app.bot import texts
from app.bot.utils import friendly_error, is_command, resolve_message_text
from app.core.logging import get_logger
from app.models.business import BusinessAdmin
from app.repositories.business import BusinessRepository, KnowledgeBaseRepository

log = get_logger(__name__)
router = Router(name="freeform")

#: Menu buttons are handled elsewhere — never treat them as knowledge.
MENU_LABELS = {
    "📅 Haftalik reja",
    "⏳ Ko'rib chiqish",
    "⚡️ Tezkor post",
    "📊 Holat",
    "🧠 Bilim bazasi",
    "ℹ️ Yordam",
}


@router.message(F.voice | F.audio | F.text)
async def freeform(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    admin: BusinessAdmin | None,
) -> None:
    if await state.get_state() is not None:
        return  # an active FSM flow owns this update
    if message.text and (message.text in MENU_LABELS or is_command(message.text)):
        return
    if admin is None:
        # A stranger writing in is a potential customer, not an error.
        from app.bot.handlers.lead import start_lead_flow

        await start_lead_flow(message, state, session)
        return

    text = await resolve_message_text(bot, message)
    if not text:
        return

    business = await BusinessRepository(session).get(admin.business_id)
    if business is None:
        await message.answer(texts.ERROR_GENERIC)
        return

    knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
    try:
        result = await OnboardingAgent(session=session).ingest(business, knowledge, text, source="freeform")
    except Exception as exc:
        log.error("freeform_ingest_failed", error=str(exc)[:300])
        await message.answer(friendly_error(exc))
        return

    await session.flush()
    await message.answer(
        texts.ONBOARDING_SAVED.format(
            summary=result.summary, progress=OnboardingAgent.progress_text(knowledge)
        )
    )


@router.message(F.document)
async def document(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    admin: BusinessAdmin | None,
) -> None:
    """An uploaded PDF is knowledge too — price lists, brandbooks, brochures."""
    if await state.get_state() is not None:
        return  # an active FSM flow owns this update
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return

    doc = message.document
    if doc is None or (doc.mime_type or "") != "application/pdf":
        await message.answer(texts.DOCUMENT_UNSUPPORTED)
        return
    if (doc.file_size or 0) > MAX_DOCUMENT_BYTES:
        await message.answer(texts.DOCUMENT_TOO_LARGE)
        return

    business = await BusinessRepository(session).get(admin.business_id)
    if business is None:
        await message.answer(texts.ERROR_GENERIC)
        return

    status = await message.answer(texts.DOCUMENT_PROCESSING)
    file = await bot.get_file(doc.file_id)
    buffer = io.BytesIO()
    await bot.download_file(file.file_path or "", buffer)

    knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
    try:
        result = await OnboardingAgent(session=session).ingest_document(
            business,
            knowledge,
            buffer.getvalue(),
            filename=doc.file_name or "document.pdf",
            source="telegram",
        )
    except Exception as exc:
        log.error("document_ingest_failed", error=str(exc)[:300])
        await status.edit_text(friendly_error(exc))
        return

    await session.flush()
    with contextlib.suppress(Exception):  # editing the status card is cosmetic
        await status.delete()
    await message.answer(
        texts.ONBOARDING_SAVED.format(
            summary=result.summary, progress=OnboardingAgent.progress_text(knowledge)
        )
    )
