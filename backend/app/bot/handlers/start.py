"""/start, /help and the main menu."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.onboarding import INTERVIEW_QUESTIONS, OnboardingAgent
from app.bot import texts
from app.bot.keyboards import BizCB, NavCB, business_picker, main_menu, onboarding_keyboard
from app.bot.states import OnboardingStates
from app.core.logging import get_logger
from app.models.business import BusinessAdmin
from app.models.enums import AdminRole, BusinessCategory
from app.repositories.business import AdminRepository, BusinessRepository, KnowledgeBaseRepository

log = get_logger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    admins: list[BusinessAdmin],
    admin: BusinessAdmin | None,
) -> None:
    await state.clear()

    if not admins or admin is None:
        await state.set_state(OnboardingStates.waiting_business_name)
        await message.answer(texts.START_NEW_USER)
        return

    knowledge = await KnowledgeBaseRepository(session).get_or_create(admin.business_id)
    await message.answer(
        texts.START_KNOWN_USER.format(
            name=message.from_user.first_name if message.from_user else "admin",
            business=admin.business.name,
            progress=OnboardingAgent.progress_text(knowledge),
        ),
        reply_markup=main_menu(),
    )

    if len(admins) > 1:
        await message.answer(
            "Bir nechta biznesga ulangansiz. Faolini tanlang:",
            reply_markup=business_picker([(a.business_id, a.business.name) for a in admins]),
        )


@router.message(OnboardingStates.waiting_business_name, F.text)
async def create_business(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """First contact: create the business, its KB and the owner membership."""
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Iltimos, biznes nomini to'liqroq yozing.")
        return

    businesses = BusinessRepository(session)
    business = await businesses.create_with_defaults(name=name[:160], category=BusinessCategory.EDUCATION)

    if message.from_user:
        await AdminRepository(session).upsert(
            business.id,
            message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username,
            role=AdminRole.OWNER,
        )

    await session.flush()
    await state.update_data(active_business_id=str(business.id))
    await state.set_state(OnboardingStates.waiting_answer)

    log.info("business_created_via_bot", business=str(business.id), name=name)
    await message.answer(
        texts.ONBOARDING_INTRO.format(question=INTERVIEW_QUESTIONS[0][1]),
        reply_markup=onboarding_keyboard(can_finish=False),
    )


@router.callback_query(BizCB.filter(F.action == "select"))
async def select_business(
    callback: CallbackQuery, callback_data: BizCB, state: FSMContext, session: AsyncSession
) -> None:
    business = await BusinessRepository(session).get(callback_data.business_id)
    if business is None:
        await callback.answer("Topilmadi", show_alert=True)
        return
    await state.update_data(active_business_id=str(business.id))
    await callback.answer(f"✅ {business.name}")
    if callback.message:
        await callback.message.answer(f"Faol biznes: <b>{business.name}</b>", reply_markup=main_menu())


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Yordam")
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP, reply_markup=main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await message.answer(texts.CANCELLED, reply_markup=main_menu())


@router.callback_query(NavCB.filter(F.action == "cancel"))
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await callback.answer(texts.CANCELLED)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
