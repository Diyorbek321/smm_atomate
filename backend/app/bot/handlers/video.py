"""Owner sends footage → the editor polishes it → it lands in the review queue.

The same router also stocks the footage shelf (`/footage`): clips the business
already owns are the only honest source for the families that put a real person
on screen, and until this existed there was no way to get them out of a phone
and into the library.

Registered before the catch-all so a video is never mistaken for a voice note
or an unsupported document.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.states import FootageStates
from app.bot.utils import is_command
from app.core.config import settings
from app.core.logging import get_logger
from app.models.business import BusinessAdmin
from app.repositories.business import BusinessRepository
from app.services.brand_assets import (
    VIDEO_SUFFIXES,
    footage_library,
    footage_shelf,
    own_footage,
)
from app.services.storage import get_storage

log = get_logger(__name__)

router = Router(name="video")

#: Telegram itself refuses to hand a bot anything larger, unless the deployment
#: runs its own Bot API server — see `settings.telegram_api_base`.
CLOUD_DOWNLOAD_LIMIT = 20 * 1024 * 1024
LOCAL_DOWNLOAD_LIMIT = 2 * 1024 * 1024 * 1024

#: Beyond this the edit takes long enough that the owner assumes it broke.
MAX_SOURCE_SECONDS = 15 * 60

#: A scene shows a few seconds of a clip, so a long recording buys nothing and
#: costs volume space on every backup.
MAX_SHELF_SECONDS = 3 * 60

#: The shelf is sampled by index, not searched: past a couple of dozen clips a
#: new one is simply unlikely to ever be picked.
MAX_SHELF_CLIPS = 24


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


async def _download(bot: Bot, file_id: str) -> bytes | None:
    """Pull a file off Telegram, or `None` when the transfer failed."""
    try:
        file = await bot.get_file(file_id)
        buffer = io.BytesIO()
        await bot.download_file(file.file_path or "", buffer)
    except Exception as exc:
        log.error("video_download_failed", error=str(exc)[:300])
        return None
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Footage shelf
# --------------------------------------------------------------------------- #
@router.message(Command("footage"))
async def cmd_footage(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    admin: BusinessAdmin | None,
) -> None:
    """Open the shelf so the next few videos are stored instead of edited."""
    if admin is None:
        await message.answer(texts.NOT_REGISTERED)
        return

    business = await BusinessRepository(session).get_full(admin.business_id)
    if business is None:
        await message.answer(texts.ERROR_GENERIC)
        return
    if not business.capabilities.video:
        await message.answer(texts.FOOTAGE_PLAN_REQUIRED)
        return

    await state.set_state(FootageStates.waiting_clips)
    await message.answer(
        texts.FOOTAGE_PROMPT.format(count=len(footage_library(business.id)))
    )


@router.message(
    FootageStates.waiting_clips,
    F.video | F.video_note | (F.document & F.document.mime_type.startswith("video/")),
)
async def collect_footage(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    admin: BusinessAdmin | None,
) -> None:
    """Store one clip on the shelf. The state stays open for the next one."""
    if admin is None:
        await state.set_state(None)
        await message.answer(texts.NOT_REGISTERED)
        return

    payload = _video_payload(message)
    if payload is None:                            # pragma: no cover - filter guarantees it
        await message.answer(texts.FOOTAGE_WRONG_TYPE)
        return
    file_id, size, filename, seconds = payload

    business = await BusinessRepository(session).get_full(admin.business_id)
    if business is None:
        await message.answer(texts.ERROR_GENERIC)
        return

    if len(own_footage(business.id)) >= MAX_SHELF_CLIPS:
        await message.answer(texts.FOOTAGE_FULL.format(limit=MAX_SHELF_CLIPS))
        return

    limit = download_limit()
    if size > limit:
        await message.answer(texts.VIDEO_TOO_LARGE.format(limit=limit // (1024 * 1024)))
        return
    if seconds > MAX_SHELF_SECONDS:
        await message.answer(texts.VIDEO_TOO_LONG.format(minutes=MAX_SHELF_SECONDS // 60))
        return

    data = await _download(bot, file_id)
    if data is None:
        await message.answer(texts.VIDEO_DOWNLOAD_FAILED)
        return

    suffix = Path(filename).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        # Telegram hands `.tmp` names for compressed video and video notes; the
        # shelf lookup filters on the suffix, so an unknown one is invisible.
        suffix = ".mp4"
    shelf = footage_shelf(business.id)
    shelf.mkdir(parents=True, exist_ok=True)
    target = shelf / f"clip_{uuid.uuid4().hex[:10]}{suffix}"
    target.write_bytes(data)

    log.info(
        "footage_stored",
        business=str(business.id),
        file=target.name,
        bytes=len(data),
        seconds=seconds,
    )
    await message.answer(
        texts.FOOTAGE_SAVED.format(count=len(footage_library(business.id)))
    )


@router.message(FootageStates.waiting_clips)
async def footage_wrong_type(message: Message) -> None:
    """Anything that is not a video while the shelf is open.

    Swallowing the update is deliberate: the freeform handler would otherwise
    file a stray caption away as business knowledge.
    """
    if is_command(message.text or ""):
        return
    await message.answer(texts.FOOTAGE_WRONG_TYPE)


# --------------------------------------------------------------------------- #
# Editing an uploaded clip
# --------------------------------------------------------------------------- #
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
    data = await _download(bot, file_id)
    if data is None:
        await status.edit_text(texts.VIDEO_DOWNLOAD_FAILED)
        return

    stored = get_storage().save_bytes(data, prefix="upload", content_type="video/mp4")
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
