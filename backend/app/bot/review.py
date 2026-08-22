"""Presenting content items to admins for approval and updating those cards."""

from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputMediaPhoto, Message

from app.bot import texts
from app.bot.keyboards import batch_keyboard, review_keyboard
from app.core.logging import get_logger
from app.models.business import Business
from app.models.content_item import ContentItem
from app.models.content_plan import ContentPlan
from app.models.enums import ContentType
from app.services.storage import local_media_path
from app.utils.dates import humanize
from app.utils.text import TG_CAPTION_LIMIT, TG_MESSAGE_LIMIT, truncate_caption

log = get_logger(__name__)


def media_source(url: str | None) -> Any | None:
    """Return an upload-friendly source for a media URL.

    Files we generated live on local disk; uploading the bytes avoids the
    "Telegram cannot reach localhost" problem during development.
    """
    if not url:
        return None
    local = local_media_path(url)
    return FSInputFile(str(local)) if local is not None else url


def format_review_caption(item: ContentItem, business: Business) -> str:
    """Header + the actual post text, trimmed to Telegram's caption limit."""
    header = texts.REVIEW_HEADER.format(
        emoji=texts.type_label(item.content_type).split(" ")[0],
        title=item.short_title(70),
        content_type=texts.type_label(item.content_type),
        pillar=texts.pillar_label(item.pillar),
        scheduled=humanize(item.scheduled_at, business.timezone),
        quality=f"{item.quality_score:.1f}",
        quality_bar=texts.quality_bar(item.quality_score),
    )

    body = item.caption_tg or item.headline
    if item.content_type == ContentType.TELEGRAM_QUIZ and item.options:
        quiz = item.options
        answers = "\n".join(
            f"{'✅' if index == quiz.get('correct_option_id', 0) else '▫️'} {answer}"
            for index, answer in enumerate(quiz.get("answers", []))
        )
        body = f"<b>{quiz.get('question', '')}</b>\n\n{answers}\n\n<i>{quiz.get('explanation', '')}</i>"
    elif item.content_type == ContentType.REELS_SCRIPT and item.script:
        scenes = item.script.get("scenes", [])[:5]
        body = "\n".join(f"<b>{s.get('t', '')}</b> — {s.get('on_screen', '')}" for s in scenes) or body

    issues = (item.editor_report or {}).get("issues") or []
    warning = ""
    critical = [i for i in issues if isinstance(i, dict) and i.get("severity") in ("critical", "major")]
    if critical:
        warning = "\n⚠️ <i>" + "; ".join(str(i.get("problem", ""))[:60] for i in critical[:2]) + "</i>"

    return truncate_caption(f"{header}\n{body}{warning}", TG_CAPTION_LIMIT)


async def send_item_for_review(bot: Bot, item: ContentItem, business: Business, chat_id: int) -> int | None:
    """Send one item with the approve/edit/regenerate keyboard.

    Returns the message id that carries the keyboard (used for later edits).
    """
    caption = format_review_caption(item, business)
    keyboard = review_keyboard(item.id)

    try:
        slide_urls = item.slide_image_urls
        if item.content_type == ContentType.CAROUSEL and len(slide_urls) >= 2:
            media = [
                InputMediaPhoto(media=media_source(url))
                for url in slide_urls[:10]
                if media_source(url) is not None
            ]
            if media:
                await bot.send_media_group(chat_id, media=media)
            message = await bot.send_message(chat_id, caption, reply_markup=keyboard)
            return message.message_id

        # A clip has to be watchable in the card — sending its poster instead
        # would ask the owner to approve something they cannot see.
        video = media_source(item.video_url)
        if video is not None:
            message = await bot.send_video(
                chat_id,
                video=video,
                caption=caption,
                reply_markup=keyboard,
                supports_streaming=True,
            )
            return message.message_id

        source = media_source(item.image_url)
        if source is not None:
            message = await bot.send_photo(chat_id, photo=source, caption=caption, reply_markup=keyboard)
        else:
            message = await bot.send_message(chat_id, caption, reply_markup=keyboard)
        return message.message_id
    except TelegramBadRequest as exc:
        log.error("review_send_failed", item=str(item.id), error=str(exc)[:300])
        try:
            message = await bot.send_message(
                chat_id, truncate_caption(caption, TG_MESSAGE_LIMIT), reply_markup=keyboard
            )
            return message.message_id
        except Exception:
            return None
    except Exception as exc:
        log.error("review_send_crashed", item=str(item.id), error=str(exc)[:300])
        return None


async def send_plan_summary(bot: Bot, plan: ContentPlan, business: Business, chat_id: int) -> int | None:
    """One-click weekly batch approval message."""
    items = plan.items or []
    strategy = plan.strategy or {}
    distribution = ", ".join(
        f"{texts.pillar_label(item_pillar)} {count}"
        for item_pillar, count in _pillar_counts(items).items()
    )
    quality = round(sum(i.quality_score for i in items) / len(items), 1) if items else 0.0

    text = texts.PLAN_READY.format(
        title=plan.label,
        theme=strategy.get("theme", "—"),
        count=len(items),
        distribution=distribution or "—",
        quality=quality,
    )
    message = await bot.send_message(chat_id, text, reply_markup=batch_keyboard(plan.id, len(items)))
    return message.message_id


def _pillar_counts(items: list[ContentItem]) -> dict[Any, int]:
    counts: dict[Any, int] = {}
    for item in items:
        counts[item.pillar] = counts.get(item.pillar, 0) + 1
    return counts


def plan_list_text(plan: ContentPlan, business: Business) -> str:
    """Compact list of every post in a plan."""
    lines = [f"📋 <b>{plan.label}</b>\n"]
    for index, item in enumerate(plan.items or [], start=1):
        lines.append(
            f"{index}. {texts.type_label(item.content_type)} · {texts.pillar_label(item.pillar)}\n"
            f"    <i>{item.short_title(52)}</i>\n"
            f"    🕐 {humanize(item.scheduled_at, business.timezone)} · {texts.status_label(item.status)}"
        )
    return truncate_caption("\n".join(lines), TG_MESSAGE_LIMIT)


async def update_review_message(
    bot: Bot, message: Message, item: ContentItem, business: Business, *, note: str = ""
) -> None:
    """Refresh an existing review card in place after an edit/regeneration."""
    caption = format_review_caption(item, business)
    if note:
        caption = truncate_caption(f"{caption}\n\n{note}", TG_CAPTION_LIMIT)
    keyboard = review_keyboard(item.id)
    try:
        if message.photo:
            await message.edit_caption(caption=caption, reply_markup=keyboard)
        else:
            await message.edit_text(caption, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        log.warning("review_update_failed_resend", error=str(exc)[:200])
        await send_item_for_review(bot, item, business, message.chat.id)


async def mark_decided(message: Message, text: str) -> None:
    """Strip the keyboard and stamp the decision onto the card."""
    try:
        if message.photo:
            existing = message.caption or ""
            await message.edit_caption(
                caption=truncate_caption(f"{existing}\n\n{text}", TG_CAPTION_LIMIT), reply_markup=None
            )
        else:
            existing = message.text or ""
            await message.edit_text(
                truncate_caption(f"{existing}\n\n{text}", TG_MESSAGE_LIMIT), reply_markup=None
            )
    except TelegramBadRequest as exc:  # pragma: no cover - cosmetic only
        log.debug("mark_decided_failed", error=str(exc)[:160])
