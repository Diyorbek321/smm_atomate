"""Knowledge-base interview — accepts text and voice answers."""

from __future__ import annotations

import contextlib

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.onboarding import OnboardingAgent
from app.bot import texts
from app.bot.keyboards import MENU_TEXTS, NavCB, main_menu, onboarding_keyboard
from app.bot.states import OnboardingStates
from app.bot.utils import friendly_error, is_command, resolve_message_text
from app.core.logging import get_logger
from app.models.business import BusinessAdmin
from app.repositories.business import BusinessRepository, KnowledgeBaseRepository

log = get_logger(__name__)
router = Router(name="onboarding")

#: Completeness at which the owner may finish the interview early.
FINISH_THRESHOLD = 0.7


async def _resolve_business_id(
    state: FSMContext,
    admin: BusinessAdmin | None,
    admins: list[BusinessAdmin] | None = None,
) -> str | None:
    """Which business these answers belong to.

    The stored id is preferred because a multi-business owner picks an active
    one — but it lives in client-held FSM state, so it is only trusted when it
    names a business the sender actually administers. Otherwise the knowledge
    base written here could be someone else's.
    """
    data = await state.get_data()
    stored = data.get("active_business_id")
    if stored:
        allowed = {str(a.business_id) for a in (admins or ([admin] if admin else []))}
        if str(stored) in allowed:
            return str(stored)
        # A freshly created business is legitimate: the membership row exists
        # but this request's `admins` was resolved before it was written.
        if admin is None and not admins:
            return str(stored)
    return str(admin.business_id) if admin else None


@router.message(OnboardingStates.waiting_answer, ~F.text.startswith("/"), ~F.text.in_(MENU_TEXTS))
async def handle_answer(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    admin: BusinessAdmin | None,
    admins: list[BusinessAdmin] | None = None,
) -> None:
    business_id = await _resolve_business_id(state, admin, admins)
    if not business_id:
        await message.answer(texts.NOT_REGISTERED)
        await state.set_state(None)
        return

    text = await resolve_message_text(bot, message)
    if not text or is_command(text):
        await message.answer("Iltimos, matn yoki ovozli xabar yuboring.")
        return

    import uuid

    business = await BusinessRepository(session).get(uuid.UUID(business_id))
    if business is None:
        await message.answer(texts.ERROR_GENERIC)
        await state.set_state(None)
        return

    knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
    agent = OnboardingAgent(session=session)

    try:
        result = await agent.ingest(business, knowledge, text, source="telegram")
    except Exception as exc:
        log.error("onboarding_ingest_failed", error=str(exc)[:300])
        await message.answer(friendly_error(exc))
        return

    await session.flush()
    progress = OnboardingAgent.progress_text(knowledge)

    if result.next_question:
        await message.answer(
            texts.ONBOARDING_NEXT.format(
                summary=result.summary, progress=progress, question=result.next_question
            ),
            reply_markup=onboarding_keyboard(can_finish=result.completeness >= FINISH_THRESHOLD),
        )
        return

    await state.set_state(None)
    await message.answer(texts.ONBOARDING_DONE.format(progress=progress), reply_markup=main_menu())


@router.callback_query(OnboardingStates.waiting_answer, NavCB.filter(F.action == "skip"))
async def skip_question(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    admin: BusinessAdmin | None,
    admins: list[BusinessAdmin] | None = None,
) -> None:
    business_id = await _resolve_business_id(state, admin, admins)
    if not business_id:
        await callback.answer(texts.NOT_REGISTERED, show_alert=True)
        return

    import uuid

    knowledge = await KnowledgeBaseRepository(session).get_or_create(uuid.UUID(business_id))
    skipped = set((await state.get_data()).get("skipped", []))
    question = OnboardingAgent.fallback_question(knowledge)

    # Walk to the next unseen question so "skip" never loops on the same one.
    from app.agents.onboarding import INTERVIEW_QUESTIONS

    remaining = [q for field, q in INTERVIEW_QUESTIONS if q not in skipped and q != question]
    if question:
        skipped.add(question)
    await state.update_data(skipped=list(skipped))

    await callback.answer("O'tkazib yuborildi")
    if not remaining or not callback.message:
        await state.set_state(None)
        if callback.message:
            await callback.message.answer(
                texts.ONBOARDING_DONE.format(progress=OnboardingAgent.progress_text(knowledge)),
                reply_markup=main_menu(),
            )
        return

    await callback.message.answer(
        f"<b>Keyingi savol:</b> {remaining[0]}",
        reply_markup=onboarding_keyboard(can_finish=knowledge.completeness_score >= FINISH_THRESHOLD),
    )


@router.callback_query(NavCB.filter(F.action == "finish_onboarding"))
async def finish_onboarding(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    admin: BusinessAdmin | None,
    admins: list[BusinessAdmin] | None = None,
) -> None:
    business_id = await _resolve_business_id(state, admin, admins)
    await state.set_state(None)
    await callback.answer("✅")
    if not (business_id and callback.message):
        return

    import uuid

    knowledge = await KnowledgeBaseRepository(session).get_or_create(uuid.UUID(business_id))

    # Queue the brand's 3D prop shelf. Six renders take a minute or so, which
    # is a minute the owner should not spend watching a Telegram spinner — and
    # nothing downstream blocks on it, so a failure here is invisible.
    with contextlib.suppress(Exception):
        from app.tasks.generation import render_brand_props

        render_brand_props.delay(business_id)

    await callback.message.answer(
        texts.ONBOARDING_DONE.format(progress=OnboardingAgent.progress_text(knowledge)),
        reply_markup=main_menu(),
    )
