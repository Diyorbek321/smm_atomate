"""Approval stream: approve / edit / regenerate / reject / reschedule."""

from __future__ import annotations

import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.feedback import FeedbackAgent
from app.bot import texts
from app.bot.keyboards import MENU_TEXTS, BatchCB, ReviewCB
from app.bot.review import mark_decided, plan_list_text, send_item_for_review
from app.bot.states import ReviewStates
from app.bot.utils import friendly_error, parse_datetime, resolve_message_text
from app.core.logging import get_logger
from app.models.business import BusinessAdmin
from app.models.content_item import ContentItem
from app.models.enums import TERMINAL_ITEM_STATUSES, ContentItemStatus
from app.repositories.business import BusinessRepository
from app.repositories.content import ContentItemRepository, ContentPlanRepository
from app.utils.dates import humanize, utcnow

log = get_logger(__name__)

#: Offered so a required field does not teach owners to type a full stop.
SKIP_COMMAND = "/skip"
router = Router(name="review")

REVIEW_BATCH_SIZE = 5


async def _load_item(session: AsyncSession, item_id: uuid.UUID, admin: BusinessAdmin | None) -> ContentItem | None:
    """Fetch an item and verify the caller may act on it."""
    item = await ContentItemRepository(session).get(item_id)
    if item is None:
        return None
    if admin is not None and item.business_id != admin.business_id:
        return None
    return item


# --------------------------------------------------------------------------- #
# /review — send the pending queue
# --------------------------------------------------------------------------- #
@router.message(Command("review"))
@router.message(F.text == "⏳ Ko'rib chiqish")
async def cmd_review(
    message: Message, session: AsyncSession, bot: Bot, admin: BusinessAdmin | None
) -> None:
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return

    repo = ContentItemRepository(session)
    pending = list(await repo.pending_review(business_id=admin.business_id, limit=REVIEW_BATCH_SIZE))
    if not pending:
        await message.answer(texts.NO_PENDING)
        return

    business = await BusinessRepository(session).get_full_or_404(admin.business_id)
    for item in pending:
        message_id = await send_item_for_review(bot, item, business, message.chat.id)
        if message_id:
            item.review_message_id = message_id
            item.review_chat_id = message.chat.id
            item.sent_for_review = True
    await session.flush()


# --------------------------------------------------------------------------- #
# Single item actions
# --------------------------------------------------------------------------- #
@router.callback_query(ReviewCB.filter(F.action == "approve"))
async def approve_item(
    callback: CallbackQuery,
    callback_data: ReviewCB,
    session: AsyncSession,
    admin: BusinessAdmin | None,
) -> None:
    item = await _load_item(session, callback_data.item_id, admin)
    if item is None:
        await callback.answer(texts.ITEM_NOT_FOUND, show_alert=True)
        return
    if item.status in TERMINAL_ITEM_STATUSES:
        await callback.answer(
            texts.ITEM_ALREADY_HANDLED.format(status=texts.status_label(item.status)), show_alert=True
        )
        return

    item.status = ContentItemStatus.APPROVED
    item.reviewed_at = utcnow()
    item.reviewed_by = callback.from_user.id if callback.from_user else None
    await session.flush()

    business = await BusinessRepository(session).get(item.business_id)
    scheduled = humanize(item.scheduled_at, business.timezone if business else None)
    await callback.answer("✅ Tasdiqlandi")
    if callback.message:
        await mark_decided(callback.message, texts.ITEM_APPROVED.format(scheduled=scheduled))
    log.info("item_approved", item=str(item.id), by=item.reviewed_by)


@router.callback_query(ReviewCB.filter(F.action == "reject"))
async def reject_item(
    callback: CallbackQuery,
    callback_data: ReviewCB,
    state: FSMContext,
    session: AsyncSession,
    admin: BusinessAdmin | None,
) -> None:
    """Ask why before throwing the post away.

    The rejection itself waits for the answer. What the owner objects to is the
    only signal this system gets about their taste, and pressing the button
    used to discard it — every rejected row in the database carries the
    planner's own note and not one sentence from a person.
    """
    item = await _load_item(session, callback_data.item_id, admin)
    if item is None:
        await callback.answer(texts.ITEM_NOT_FOUND, show_alert=True)
        return

    await state.set_state(ReviewStates.waiting_reject_reason)
    await state.update_data(reject_item_id=str(item.id))
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.REJECT_WHY)


# `/skip` must reach the handler, so slash commands are not blocked wholesale —
# but a menu button is a navigation press, and recording its label as the reason
# would fill the column this exists to fill with "📋 Rejalar".
@router.message(
    ReviewStates.waiting_reject_reason,
    F.text,
    ~F.text.in_(MENU_TEXTS),
    (F.text == SKIP_COMMAND) | ~F.text.startswith("/"),
)
async def reject_reason(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    admin: BusinessAdmin | None,
) -> None:
    """Record the reason, then reject.

    `/skip` is offered on purpose: a required field teaches owners to type a
    full stop, and a column of full stops is worse than a column of blanks —
    it looks like data.
    """
    data = await state.get_data()
    raw = str(getattr(message, "text", "") or "").strip()
    await state.set_state(None)

    item_id = data.get("reject_item_id")
    if not item_id:
        await message.answer(texts.REJECT_NO_ITEM)
        return

    item = await _load_item(session, uuid.UUID(str(item_id)), admin)
    if item is None:
        await message.answer(texts.ITEM_NOT_FOUND)
        return

    reason = "" if raw == SKIP_COMMAND else raw[:2000]
    item.status = ContentItemStatus.REJECTED
    item.reviewed_at = utcnow()
    item.reviewed_by = message.from_user.id if message.from_user else None
    item.review_notes = reason
    await session.flush()

    log.info(
        "item_rejected", item=str(item.id), with_reason=bool(reason), chars=len(reason)
    )
    await message.answer(texts.ITEM_REJECTED)


@router.callback_query(ReviewCB.filter(F.action == "edit"))
async def start_edit(
    callback: CallbackQuery,
    callback_data: ReviewCB,
    state: FSMContext,
    session: AsyncSession,
    admin: BusinessAdmin | None,
) -> None:
    item = await _load_item(session, callback_data.item_id, admin)
    if item is None:
        await callback.answer(texts.ITEM_NOT_FOUND, show_alert=True)
        return

    await state.set_state(ReviewStates.waiting_edit_instruction)
    await state.update_data(
        editing_item_id=str(item.id),
        review_chat_id=callback.message.chat.id if callback.message else None,
        review_message_id=callback.message.message_id if callback.message else None,
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.EDIT_PROMPT)


@router.callback_query(ReviewCB.filter(F.action == "regen"))
async def regenerate_item(
    callback: CallbackQuery,
    callback_data: ReviewCB,
    session: AsyncSession,
    bot: Bot,
    admin: BusinessAdmin | None,
) -> None:
    item = await _load_item(session, callback_data.item_id, admin)
    if item is None:
        await callback.answer(texts.ITEM_NOT_FOUND, show_alert=True)
        return

    await callback.answer(texts.ITEM_REGENERATING)
    await _run_regeneration(
        session=session,
        bot=bot,
        item=item,
        instruction="",
        regenerate_image=True,
        chat_id=callback.message.chat.id if callback.message else None,
    )


@router.callback_query(ReviewCB.filter(F.action == "reschedule"))
async def start_reschedule(
    callback: CallbackQuery,
    callback_data: ReviewCB,
    state: FSMContext,
    session: AsyncSession,
    admin: BusinessAdmin | None,
) -> None:
    item = await _load_item(session, callback_data.item_id, admin)
    if item is None:
        await callback.answer(texts.ITEM_NOT_FOUND, show_alert=True)
        return

    await state.set_state(ReviewStates.waiting_new_datetime)
    await state.update_data(editing_item_id=str(item.id))
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.RESCHEDULE_PROMPT)


# --------------------------------------------------------------------------- #
# Edit / reschedule follow-ups (text OR voice)
# --------------------------------------------------------------------------- #
@router.message(ReviewStates.waiting_edit_instruction, ~F.text.startswith("/"), ~F.text.in_(MENU_TEXTS))
async def apply_edit(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    admin: BusinessAdmin | None,
) -> None:
    data = await state.get_data()
    item_id = data.get("editing_item_id")
    if not item_id:
        await state.set_state(None)
        await message.answer(texts.ITEM_NOT_FOUND)
        return

    instruction = await resolve_message_text(bot, message)
    if not instruction:
        await message.answer("Iltimos, o'zgartirishni yozing yoki ovozli xabar yuboring.")
        return

    item = await _load_item(session, uuid.UUID(item_id), admin)
    if item is None:
        await state.set_state(None)
        await message.answer(texts.ITEM_NOT_FOUND)
        return

    business = await BusinessRepository(session).get(item.business_id)
    parsed = await FeedbackAgent(session=session).parse(
        instruction, item=item, tz_name=business.timezone if business else None
    )
    log.info("feedback_parsed", action=parsed.action, confidence=parsed.confidence, item=str(item.id))

    if parsed.action == "reject":
        item.status = ContentItemStatus.REJECTED
        # Same bookkeeping as the button. A rejection is a decision someone
        # made, and without these it is the only decision the system cannot
        # attribute or date.
        item.reviewed_at = utcnow()
        item.reviewed_by = message.from_user.id if message.from_user else None
        item.review_notes = instruction[:2000]
        await session.flush()
        await state.set_state(None)
        await message.answer(texts.ITEM_REJECTED)
        return

    if parsed.action == "reschedule" and parsed.new_datetime:
        item.scheduled_at = parsed.new_datetime
        await session.flush()
        await state.set_state(None)
        await message.answer(
            texts.RESCHEDULED.format(scheduled=humanize(item.scheduled_at, business.timezone if business else None))
        )
        return

    item.review_notes = instruction[:2000]
    await state.set_state(None)
    await message.answer(texts.ITEM_REGENERATING)
    await _run_regeneration(
        session=session,
        bot=bot,
        item=item,
        instruction=parsed.instruction_for_writer or instruction,
        regenerate_image=parsed.action == "change_image",
        chat_id=message.chat.id,
    )


@router.message(ReviewStates.waiting_new_datetime, F.text, ~F.text.in_(MENU_TEXTS))
async def apply_reschedule(
    message: Message, state: FSMContext, session: AsyncSession, admin: BusinessAdmin | None
) -> None:
    data = await state.get_data()
    item_id = data.get("editing_item_id")
    item = await _load_item(session, uuid.UUID(item_id), admin) if item_id else None
    if item is None:
        await state.set_state(None)
        await message.answer(texts.ITEM_NOT_FOUND)
        return

    business = await BusinessRepository(session).get(item.business_id)
    tz_name = business.timezone if business else None
    when = parse_datetime(message.text or "", tz_name)
    if when is None:
        await message.answer(texts.RESCHEDULE_PROMPT)
        return

    item.scheduled_at = when
    await session.flush()
    await state.set_state(None)
    await message.answer(texts.RESCHEDULED.format(scheduled=humanize(when, tz_name)))


# --------------------------------------------------------------------------- #
# Weekly batch actions
# --------------------------------------------------------------------------- #
@router.callback_query(BatchCB.filter(F.action == "approve_all"))
async def approve_all(
    callback: CallbackQuery, callback_data: BatchCB, session: AsyncSession, admin: BusinessAdmin | None
) -> None:
    plan = await ContentPlanRepository(session).get_with_items(callback_data.plan_id)
    if plan is None or (admin and plan.business_id != admin.business_id):
        await callback.answer(texts.ITEM_NOT_FOUND, show_alert=True)
        return

    approved = 0
    reviewer = callback.from_user.id if callback.from_user else None
    for item in plan.items:
        if item.status in (ContentItemStatus.PENDING_REVIEW, ContentItemStatus.DRAFT):
            item.status = ContentItemStatus.APPROVED
            item.reviewed_at = utcnow()
            item.reviewed_by = reviewer
            approved += 1

    from app.models.enums import ContentPlanStatus

    plan.status = ContentPlanStatus.APPROVED
    await session.flush()

    await callback.answer(f"✅ {approved} ta tasdiqlandi")
    if callback.message:
        await mark_decided(callback.message, texts.BATCH_APPROVED.format(count=approved))
    log.info("batch_approved", plan=str(plan.id), count=approved)


@router.callback_query(BatchCB.filter(F.action == "reject_all"))
async def reject_all(
    callback: CallbackQuery, callback_data: BatchCB, session: AsyncSession, admin: BusinessAdmin | None
) -> None:
    plan = await ContentPlanRepository(session).get_with_items(callback_data.plan_id)
    if plan is None or (admin and plan.business_id != admin.business_id):
        await callback.answer(texts.ITEM_NOT_FOUND, show_alert=True)
        return

    rejected = 0
    reviewer = callback.from_user.id if callback.from_user else None
    for item in plan.items:
        if item.status not in TERMINAL_ITEM_STATUSES:
            item.status = ContentItemStatus.REJECTED
            item.reviewed_at = utcnow()
            item.reviewed_by = reviewer
            rejected += 1
    await session.flush()

    await callback.answer(f"🗑 {rejected}")
    if callback.message:
        await mark_decided(callback.message, texts.BATCH_REJECTED.format(count=rejected))


@router.callback_query(BatchCB.filter(F.action == "show"))
async def show_plan(
    callback: CallbackQuery, callback_data: BatchCB, session: AsyncSession, admin: BusinessAdmin | None
) -> None:
    plan = await ContentPlanRepository(session).get_with_items(callback_data.plan_id)
    if plan is None:
        await callback.answer(texts.ITEM_NOT_FOUND, show_alert=True)
        return
    business = await BusinessRepository(session).get_full_or_404(plan.business_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(plan_list_text(plan, business))


# --------------------------------------------------------------------------- #
async def _run_regeneration(
    *,
    session: AsyncSession,
    bot: Bot,
    item: ContentItem,
    instruction: str,
    regenerate_image: bool,
    chat_id: int | None,
) -> None:
    """Regenerate inline and push the refreshed card back to the reviewer."""
    from app.agents.orchestrator import ContentPipeline

    business = await BusinessRepository(session).get_full_or_404(item.business_id)
    try:
        await ContentPipeline(session).regenerate(
            item, instruction=instruction, regenerate_image=regenerate_image
        )
    except Exception as exc:
        log.error("regeneration_failed", item=str(item.id), error=str(exc)[:300])
        if chat_id:
            await bot.send_message(chat_id, friendly_error(exc))
        return

    await session.flush()
    if not chat_id:
        return

    message_id = await send_item_for_review(bot, item, business, chat_id)
    if message_id:
        item.review_message_id = message_id
        item.review_chat_id = chat_id
        item.sent_for_review = True
        await session.flush()
