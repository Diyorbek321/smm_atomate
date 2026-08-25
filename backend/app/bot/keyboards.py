"""Inline keyboards and callback-data factories for the approval bot."""

from __future__ import annotations

import uuid

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class ReviewCB(CallbackData, prefix="rev"):
    """Actions on a single content item."""

    action: str          # approve | edit | regen | reject | reschedule | preview
    item_id: uuid.UUID


class BatchCB(CallbackData, prefix="batch"):
    """Actions on a whole weekly plan."""

    action: str          # approve_all | reject_all | show
    plan_id: uuid.UUID


class BizCB(CallbackData, prefix="biz"):
    action: str          # select | generate | status | onboard
    business_id: uuid.UUID


class NavCB(CallbackData, prefix="nav"):
    action: str
    value: str = ""


def review_keyboard(item_id: uuid.UUID, *, show_reschedule: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Tasdiqlash", callback_data=ReviewCB(action="approve", item_id=item_id))
    builder.button(text="✏️ Tahrirlash", callback_data=ReviewCB(action="edit", item_id=item_id))
    builder.button(text="🔄 Qayta yaratish", callback_data=ReviewCB(action="regen", item_id=item_id))
    if show_reschedule:
        builder.button(text="🕐 Vaqtni o'zgartirish", callback_data=ReviewCB(action="reschedule", item_id=item_id))
    builder.button(text="🗑 Bekor qilish", callback_data=ReviewCB(action="reject", item_id=item_id))
    builder.adjust(2, 1, 1, 1)
    return builder.as_markup()


def batch_keyboard(plan_id: uuid.UUID, pending: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"✅ Hammasini tasdiqlash ({pending})",
        callback_data=BatchCB(action="approve_all", plan_id=plan_id),
    )
    builder.button(text="📋 Ro'yxatni ko'rish", callback_data=BatchCB(action="show", plan_id=plan_id))
    builder.button(text="🗑 Hammasini bekor qilish", callback_data=BatchCB(action="reject_all", plan_id=plan_id))
    builder.adjust(1)
    return builder.as_markup()


def business_picker(businesses: list[tuple[uuid.UUID, str]], action: str = "select") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for business_id, name in businesses[:20]:
        builder.button(text=name[:40], callback_data=BizCB(action=action, business_id=business_id))
    builder.adjust(1)
    return builder.as_markup()


def confirm_keyboard(yes_data: str, no_data: str = "nav:cancel:") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha", callback_data=yes_data),
                InlineKeyboardButton(text="❌ Yo'q", callback_data=no_data),
            ]
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Bekor qilish", callback_data=NavCB(action="cancel").pack())
    return builder.as_markup()


def onboarding_keyboard(*, can_finish: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Bu savolni o'tkazib yuborish", callback_data=NavCB(action="skip").pack())
    if can_finish:
        builder.button(text="✅ Yakunlash", callback_data=NavCB(action="finish_onboarding").pack())
    builder.button(text="❌ To'xtatish", callback_data=NavCB(action="cancel").pack())
    builder.adjust(1)
    return builder.as_markup()


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Haftalik reja"), KeyboardButton(text="⏳ Ko'rib chiqish")],
            [KeyboardButton(text="⚡️ Tezkor post"), KeyboardButton(text="🎬 Klip")],
            [KeyboardButton(text="📊 Holat"), KeyboardButton(text="🎥 Suratga olish brifi")],
            [KeyboardButton(text="📊 Oylik hisobot")],
            [KeyboardButton(text="🧠 Bilim bazasi"), KeyboardButton(text="ℹ️ Yordam")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Buyruqni tanlang yoki yozing…",
    )


#: Every label on the persistent keyboard.
#:
#: The keyboard never goes away, so a menu button is always one tap from a
#: prompt like "which topic?" — and a handler waiting on free text will happily
#: accept "📊 Holat" as the topic. Stateful text handlers exclude these, which
#: only works if the list is derived from the keyboard itself: a button added
#: below and forgotten here would be swallowed again, silently.
MENU_TEXTS: frozenset[str] = frozenset(
    button.text for row in main_menu().keyboard for button in row
)
