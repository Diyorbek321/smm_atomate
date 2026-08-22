"""Owner sends footage → the editor polishes it → it lands in the review queue.

Registered before the catch-all so a video is never mistaken for a voice note
or an unsupported document.
"""

from __future__ import annotations

import io

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.core.config import settings
from app.core.logging import get_logger
from app.models.business import BusinessAdmin
from app.repositories.business import BusinessRepository
from app.services.storage import get_storage

log = get_logger(__name__)

router = Router(name="video")

#: Telegram itself refuses to hand a bot anything larger, unless the deployment
#: runs its own Bot API server — see `settings.telegram_api_base`.
CLOUD_DOWNLOAD_LIMIT = 20 * 1024 * 1024
LOCAL_DOWNLOAD_LIMIT = 2 * 1024 * 1024 * 1024

#: Beyond this the edit takes long enough that the owner assumes it broke.
MAX_SOURCE_SECONDS = 15 * 60


def download_limit() -> int:
    return LOCAL_DOWNLOAD_LIMIT if settings.telegram_api_base else CLOUD_DOWNLOAD_LIMIT


def _video_payload(message: Message) -> tuple[str, int, str, int] | None:
    """Return `(file_id, size, filename, seconds)` for anything really a video."""
    if message.video is not None:
        return (
            message.video.file_id,
            message.video.file_size or 0,
            message.video.file_name or "upload.mp4",
            message.video.duration or 0,
        )
    if message.video_note is not None:
        return (
            message.video_note.file_id,
            message.video_note.file_size or 0,
            "note.mp4",
            message.video_note.duration or 0,
        )
    doc = message.document
    if doc is not None and (doc.mime_type or "").startswith("video/"):
        return (doc.file_id, doc.file_size or 0, doc.file_name or "upload.mp4", 0)
    return None


@router.message(F.video | F.video_note | (F.document & F.document.mime_type.startswith("video/")))
async def edit_video_upload(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    admin: BusinessAdmin | None,
) -> None:
    if await state.get_state() is not None:
        return  # an active FSM flow owns this update
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return

    payload = _video_payload(message)
    if payload is None:
        return
    file_id, size, filename, seconds = payload

    business = await BusinessRepository(session).get_full(admin.business_id)
    if business is None:
        await message.answer(texts.ERROR_GENERIC)
        return

    if not business.capabilities.video_editing:
        await message.answer(texts.VIDEO_PLAN_REQUIRED)
        return

    limit = download_limit()
    if size > limit:
        await message.answer(texts.VIDEO_TOO_LARGE.format(limit=limit // (1024 * 1024)))
        return
    if seconds > MAX_SOURCE_SECONDS:
        await message.answer(texts.VIDEO_TOO_LONG.format(minutes=MAX_SOURCE_SECONDS // 60))
        return

    status = await message.answer(texts.VIDEO_RECEIVED)
    try:
        file = await bot.get_file(file_id)
        buffer = io.BytesIO()
        await bot.download_file(file.file_path or "", buffer)
    except Exception as exc:
        log.error("video_download_failed", error=str(exc)[:300])
        await status.edit_text(texts.VIDEO_DOWNLOAD_FAILED)
        return

    stored = get_storage().save_bytes(
        buffer.getvalue(), prefix="upload", content_type="video/mp4"
    )
    caption = (message.caption or "").strip()

    from app.tasks.generation import edit_uploaded_video

    try:
        edit_uploaded_video.delay(
            str(business.id), stored.filename, caption=caption, chat_id=message.chat.id
        )
    except Exception as exc:                      # no broker → do it inline
        log.warning("video_queue_unavailable_inline", error=str(exc)[:200])
        await status.edit_text(texts.VIDEO_EDITING)
        from app.tasks.generation import run_video_edit

        await run_video_edit(str(business.id), stored.filename, caption=caption)
        await status.edit_text(texts.VIDEO_DONE)
        return

    log.info("video_edit_queued", business=str(business.id), size=size, source=filename)
    await status.edit_text(texts.VIDEO_EDITING)
