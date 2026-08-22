"""Owner commands: /plan, /quick, /status, /kb."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.onboarding import OnboardingAgent
from app.bot import texts
from app.bot.keyboards import main_menu
from app.bot.review import send_item_for_review, send_plan_summary
from app.bot.states import QuickPostStates
from app.bot.utils import friendly_error, resolve_message_text
from app.core.logging import get_logger
from app.models.business import BusinessAdmin
from app.models.enums import ContentItemStatus, ContentPillar, ContentType
from app.repositories.business import BusinessRepository, KnowledgeBaseRepository
from app.repositories.content import ContentItemRepository
from app.services.analytics import AnalyticsService, business_content_health
from app.tasks.dispatch import enqueue

log = get_logger(__name__)
router = Router(name="admin")


@router.message(Command("plan"))
@router.message(F.text == "📅 Haftalik reja")
async def cmd_plan(message: Message, session: AsyncSession, bot: Bot, admin: BusinessAdmin | None) -> None:
    if admin is None or not admin.can_approve:
        await message.answer(texts.NOT_REGISTERED)
        return

    business = await BusinessRepository(session).get_full_or_404(admin.business_id)

    # Generating a week is minutes of LLM work. The worker owns it so the chat
    # stays responsive and provider rate limits can simply be waited out.
    task_id = enqueue(
        "app.tasks.generation.generate_weekly_plan",
        str(business.id),
        send_for_review=True,
    )
    if task_id:
        await message.answer(texts.PLAN_GENERATING)
        log.info("plan_queued", business=str(business.id), task=task_id)
        return

    # No broker (single-process deployment) — fall back to doing it here.
    from app.agents.orchestrator import ContentPipeline

    await message.answer(texts.PLAN_GENERATING)
    try:
        result = await ContentPipeline(session).generate_plan(business.id)
    except Exception as exc:
        log.error("plan_generation_failed", business=str(business.id), error=str(exc)[:300])
        await message.answer(friendly_error(exc))
        return

    await session.flush()
    if result.plan is None or not result.items:
        await message.answer(texts.PLAN_FAILED.format(error="; ".join(result.failures)[:200] or "bo'sh natija"))
        return

    await send_plan_summary(bot, result.plan, business, message.chat.id)
    for item in result.items[:3]:
        message_id = await send_item_for_review(bot, item, business, message.chat.id)
        if message_id:
            item.review_message_id = message_id
            item.review_chat_id = message.chat.id
            item.sent_for_review = True
    await session.flush()


@router.message(Command("quick"))
@router.message(F.text == "⚡️ Tezkor post")
async def cmd_quick(message: Message, state: FSMContext, admin: BusinessAdmin | None) -> None:
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return
    await state.set_state(QuickPostStates.waiting_topic)
    await message.answer(texts.QUICK_PROMPT)


@router.message(QuickPostStates.waiting_topic, ~F.text.startswith("/"))
async def quick_topic(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot, admin: BusinessAdmin | None
) -> None:
    if admin is None:
        await state.set_state(None)
        await message.answer(texts.NOT_REGISTERED)
        return

    topic = await resolve_message_text(bot, message)
    if not topic:
        await message.answer(texts.QUICK_PROMPT)
        return

    await state.set_state(None)
    business = await BusinessRepository(session).get_full_or_404(admin.business_id)

    task_id = enqueue(
        "app.tasks.generation.generate_single_item",
        str(business.id),
        content_type=ContentType.FEED_POST.value,
        pillar=ContentPillar.SALES.value,
        topic=topic,
        send_for_review=True,
    )
    if task_id:
        await message.answer(texts.QUICK_GENERATING)
        return

    from app.agents.orchestrator import ContentPipeline

    await message.answer(texts.QUICK_GENERATING)
    try:
        item = await ContentPipeline(session).generate_single(
            business.id, content_type=ContentType.FEED_POST, pillar=ContentPillar.SALES, topic=topic
        )
    except Exception as exc:
        log.error("quick_generation_failed", error=str(exc)[:300])
        await message.answer(friendly_error(exc))
        return

    await session.flush()
    message_id = await send_item_for_review(bot, item, business, message.chat.id)
    if message_id:
        item.review_message_id = message_id
        item.review_chat_id = message.chat.id
        item.sent_for_review = True
        await session.flush()


@router.message(Command("status"))
@router.message(F.text == "📊 Holat")
async def cmd_status(message: Message, session: AsyncSession, admin: BusinessAdmin | None) -> None:
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return

    business = await BusinessRepository(session).get_full_or_404(admin.business_id)
    stats = await AnalyticsService(session).for_business(business.id)
    health = await business_content_health(session, business.id)
    knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)

    await message.answer(
        texts.STATUS_TEXT.format(
            business=business.name,
            pending=stats.pending_review,
            approved=health["approved_next_7d"],
            published=stats.published,
            failed=stats.failed,
            quality=stats.avg_quality_score,
            kb_progress=OnboardingAgent.progress_text(knowledge),
        ),
        reply_markup=main_menu(),
    )


@router.message(Command("kb"))
@router.message(F.text == "🧠 Bilim bazasi")
async def cmd_knowledge(message: Message, session: AsyncSession, admin: BusinessAdmin | None) -> None:
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return

    business = await BusinessRepository(session).get_full_or_404(admin.business_id)
    knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
    knowledge.compute_completeness()
    missing = knowledge.missing_fields

    await message.answer(
        texts.KB_SUMMARY.format(
            business=business.name,
            progress=OnboardingAgent.progress_text(knowledge),
            offerings=len(knowledge.key_offerings),
            prices=len(knowledge.prices),
            usps=len(knowledge.usps),
            teachers=len(knowledge.teacher_profiles),
            faq=len(knowledge.faq),
            stories=len(knowledge.success_stories),
            missing=texts.KB_MISSING.format(fields=", ".join(missing)) if missing else texts.KB_COMPLETE,
        )
    )


@router.message(Command("pending"))
async def cmd_pending_count(message: Message, session: AsyncSession, admin: BusinessAdmin | None) -> None:
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return
    counts = await ContentItemRepository(session).status_counts(admin.business_id)
    lines = [f"• {texts.status_label(ContentItemStatus(key))}: <b>{value}</b>" for key, value in counts.items()]
    await message.answer("📦 <b>Kontent holati</b>\n\n" + ("\n".join(lines) or "Bo'sh"))
