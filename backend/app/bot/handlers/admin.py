"""Owner commands: /plan, /quick, /status, /kb, /brif, /hisobot."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.onboarding import OnboardingAgent
from app.bot import texts
from app.bot.keyboards import MENU_TEXTS, main_menu
from app.bot.review import send_item_for_review, send_plan_summary
from app.bot.states import ClipStates, QuickPostStates
from app.bot.utils import friendly_error, resolve_message_text
from app.core.logging import get_logger
from app.models.business import BusinessAdmin
from app.models.enums import ContentItemStatus, ContentPillar, ContentType
from app.repositories.business import BusinessRepository, KnowledgeBaseRepository
from app.repositories.content import ContentItemRepository
from app.services.analytics import AnalyticsService, business_content_health
from app.services.brand_assets import own_footage
from app.services.client_report import build_report
from app.services.client_report import render_telegram as render_report
from app.services.shooting_brief import build_brief, render_telegram
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


@router.message(QuickPostStates.waiting_topic, ~F.text.startswith("/"), ~F.text.in_(MENU_TEXTS))
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


@router.message(Command("klip"))
@router.message(F.text == "🎬 Klip")
async def cmd_clip(message: Message, state: FSMContext, admin: BusinessAdmin | None) -> None:
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return
    await state.set_state(ClipStates.waiting_topic)
    await message.answer(texts.CLIP_PROMPT)


@router.message(ClipStates.waiting_topic, ~F.text.startswith("/"), ~F.text.in_(MENU_TEXTS))
async def clip_topic(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot,
    admin: BusinessAdmin | None
) -> None:
    """Queue a promo clip and let the worker deliver it.

    Unlike a quick post there is no inline fallback: a clip is a few minutes of
    browser rendering, which is far longer than a Telegram handler may block.
    Without a queue the honest answer is to say so.
    """
    if admin is None:
        await state.set_state(None)
        await message.answer(texts.NOT_REGISTERED)
        return

    topic = await resolve_message_text(bot, message)
    if not topic:
        await message.answer(texts.CLIP_PROMPT)
        return

    await state.set_state(None)
    business = await BusinessRepository(session).get_full_or_404(admin.business_id)
    if not business.capabilities.video:
        await message.answer(
            f"🎬 Klip «{business.plan}» tarifiga kirmaydi — Pro tarifi kerak."
        )
        return

    task_id = enqueue(
        "app.tasks.generation.render_promo_clip",
        str(business.id),
        topic=topic,
        pillar=ContentPillar.EDUCATIONAL.value,
    )
    if not task_id:
        log.warning("clip_broker_unavailable", business=str(business.id))
        await message.answer(texts.CLIP_NO_QUEUE)
        return
    await message.answer(texts.CLIP_GENERATING)


def _media_summary(business_id) -> str:
    """The visual shelves, and a warning for anything switched off.

    Both failure modes here are invisible from the outside: an unconfigured
    image provider produces flatter clips, and an empty footage shelf silently
    changes which family gets picked.
    """
    from app.services.brand_assets import media_readiness

    state = media_readiness(business_id)
    text = texts.MEDIA_READY.format(
        props=state["props"], photos=state["photos"], footage=state["footage"]
    )
    if not state["image_provider_ready"]:
        text += texts.MEDIA_PROVIDER_OFF.format(provider=state["image_provider"])
    if not state["footage"]:
        text += texts.MEDIA_NO_FOOTAGE
    return text


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
            media=_media_summary(business.id),
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


@router.message(Command("hisobot"))
@router.message(F.text == "📊 Oylik hisobot")
async def cmd_monthly_report(
    message: Message, session: AsyncSession, admin: BusinessAdmin | None
) -> None:
    """Last month, written for the person paying for it — leads first."""
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return

    business = await BusinessRepository(session).get_full_or_404(admin.business_id)
    report = await build_report(session, business)
    for chunk in _split_message(render_report(report)):
        await message.answer(chunk, parse_mode="HTML")


@router.message(Command("brif"))
@router.message(F.text == "🎥 Suratga olish brifi")
async def cmd_shooting_brief(
    message: Message, session: AsyncSession, admin: BusinessAdmin | None
) -> None:
    """This month's shot list.

    The one thing the owner has to do that nothing here can do for them: no
    template rescues footage shot in a dark corridor, and no model invents a
    photograph of their actual classroom.
    """
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return

    business = await BusinessRepository(session).get_full_or_404(admin.business_id)
    knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
    brief = build_brief(
        business, knowledge, footage_on_hand=len(own_footage(business.id))
    )

    # Telegram caps a message at 4096 characters and a full Pro brief runs
    # close to it; splitting on shot boundaries keeps each part readable.
    text = render_telegram(brief)
    for chunk in _split_message(text):
        await message.answer(chunk, parse_mode="HTML")


def _split_message(text: str, limit: int = 3800) -> list[str]:
    """Split on blank lines so a shot never lands across two messages."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit and current:
            parts.append(current)
            current = block
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


@router.message(Command("pending"))
async def cmd_pending_count(message: Message, session: AsyncSession, admin: BusinessAdmin | None) -> None:
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return
    counts = await ContentItemRepository(session).status_counts(admin.business_id)
    lines = [f"• {texts.status_label(ContentItemStatus(key))}: <b>{value}</b>" for key, value in counts.items()]
    await message.answer("📦 <b>Kontent holati</b>\n\n" + ("\n".join(lines) or "Bo'sh"))
