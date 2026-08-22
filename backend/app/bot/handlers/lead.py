"""Lead capture — a stranger who writes in is a customer, not an error.

Post CTAs say "botga yozing"; whoever follows them is greeted, asked what they
are interested in and for a phone number, then saved as a Lead and every admin
of the business is pinged. Registered admins never enter this flow.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.states import LeadStates
from app.bot.utils import is_command, resolve_message_text
from app.core.logging import get_logger
from app.models.business import Business, BusinessAdmin
from app.repositories.business import BusinessRepository
from app.repositories.lead import LeadRepository

log = get_logger(__name__)
router = Router(name="lead")


async def _single_active_business(session: AsyncSession) -> Business | None:
    rows, total = await BusinessRepository(session).search(is_active=True, offset=0, limit=2)
    return rows[0] if total == 1 else None


def _phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.LEAD_PHONE_BUTTON, request_contact=True)],
            [KeyboardButton(text=texts.LEAD_SKIP_BUTTON)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def start_lead_flow(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Entry point — called by the catch-all when the sender is not an admin."""
    business = await _single_active_business(session)
    if business is not None and not business.capabilities.lead_autoreply:
        log.info("lead_flow_skipped_plan", plan=str(business.plan))
        return
    await state.set_state(LeadStates.waiting_interest)
    await state.update_data(lead_business_id=str(business.id) if business else "")
    await message.answer(
        texts.LEAD_WELCOME.format(business=business.name if business else "o'quv markazimiz")
    )


@router.message(LeadStates.waiting_interest, F.text | F.voice | F.audio)
async def lead_interest(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    if message.text and is_command(message.text):
        return
    interest = await resolve_message_text(bot, message) or ""
    await state.update_data(lead_interest=interest[:2000])
    await state.set_state(LeadStates.waiting_phone)
    await message.answer(texts.LEAD_ASK_PHONE, reply_markup=_phone_keyboard())


@router.message(LeadStates.waiting_phone, F.contact | F.text)
async def lead_phone(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot,
    admin: BusinessAdmin | None,
) -> None:
    if message.text and is_command(message.text):
        return
    phone = ""
    if message.contact is not None:
        phone = message.contact.phone_number or ""
    elif message.text and message.text != texts.LEAD_SKIP_BUTTON:
        phone = message.text.strip()[:64]

    data = await state.get_data()
    await state.clear()

    business_id = None
    raw_business = data.get("lead_business_id") or ""
    if raw_business:
        import uuid

        business_id = uuid.UUID(raw_business)

    user = message.from_user
    lead = await LeadRepository(session).add(
        business_id=business_id,
        telegram_user_id=user.id if user else 0,
        full_name=(user.full_name if user else "") or "",
        username=(f"@{user.username}" if user and user.username else ""),
        phone=phone,
        interest=str(data.get("lead_interest") or ""),
    )
    await session.flush()
    await message.answer(texts.LEAD_THANKS, reply_markup=ReplyKeyboardRemove())

    if business_id is not None:
        try:
            from app.bot.notifier import notify_admins  # lazy: avoids bot.main import cycle

            await notify_admins(
                session,
                business_id,
                texts.LEAD_NOTIFY.format(
                    name=lead.full_name or "Noma'lum",
                    username=lead.username,
                    phone=lead.phone or "ko'rsatilmagan",
                    interest=lead.interest or "aytilmagan",
                ),
            )
        except Exception as exc:  # notification is best-effort, the lead is saved
            log.warning("lead_notify_failed", error=str(exc)[:200])
    log.info("lead_captured", lead=str(lead.id), business=str(business_id), has_phone=bool(phone))
