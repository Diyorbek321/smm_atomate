"""Shared helpers for bot handlers."""

from __future__ import annotations

import contextlib
import io
import re
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.types import Message

from app.bot import texts
from app.core.logging import get_logger
from app.services.transcription import get_transcriber
from app.utils.dates import get_tz, to_utc, utcnow

log = get_logger(__name__)

#: Voice notes longer than this are rejected (Telegram allows up to 20 MB).
MAX_VOICE_BYTES = 20 * 1024 * 1024

_TIME_ONLY = re.compile(r"^(\d{1,2})[:.](\d{2})$")
_FULL_DATE = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})\s+(\d{1,2})[:.](\d{2})$")
_SHORT_DATE = re.compile(r"^(\d{1,2})[./](\d{1,2})\s+(\d{1,2})[:.](\d{2})$")


async def download_voice(bot: Bot, message: Message) -> tuple[bytes, str] | None:
    """Fetch the voice/audio payload of a message."""
    media = message.voice or message.audio or message.video_note
    if media is None:
        return None
    if getattr(media, "file_size", 0) and media.file_size > MAX_VOICE_BYTES:
        return None

    file = await bot.get_file(media.file_id)
    if not file.file_path:
        return None
    buffer = io.BytesIO()
    await bot.download_file(file.file_path, buffer)
    mime = getattr(media, "mime_type", None) or "audio/ogg"
    return buffer.getvalue(), mime


async def resolve_message_text(bot: Bot, message: Message, *, notify: bool = True) -> str | None:
    """Return the message text, transcribing voice notes when necessary."""
    if message.text:
        return message.text.strip()
    if message.caption:
        return message.caption.strip()

    payload = await download_voice(bot, message)
    if payload is None:
        return None

    audio, mime = payload
    status = await message.answer(texts.VOICE_PROCESSING) if notify else None
    try:
        transcript = await get_transcriber().transcribe(audio, mime_type=mime)
    except Exception as exc:
        log.error("voice_transcription_failed", error=str(exc)[:300])
        if status:
            await status.edit_text(texts.VOICE_FAILED)
        return None

    if status:
        with contextlib.suppress(Exception):  # editing the status card is cosmetic
            await status.edit_text(texts.VOICE_HEARD.format(text=transcript[:600]))
    return transcript.strip()


def parse_datetime(text: str, tz_name: str | None = None) -> datetime | None:
    """Parse `18:00`, `25.08.2026 18:00` or `25.08 18:00` into an aware UTC value."""
    text = (text or "").strip()
    tz = get_tz(tz_name)
    now_local = utcnow().astimezone(tz)

    match = _TIME_ONLY.match(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        candidate = now_local.replace(hour=min(hour, 23), minute=min(minute, 59), second=0, microsecond=0)
        if candidate <= now_local:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)

    match = _FULL_DATE.match(text)
    if match:
        day, month, year, hour, minute = (int(g) for g in match.groups())
        try:
            naive = datetime(year, month, day, min(hour, 23), min(minute, 59))
        except ValueError:
            return None
        return to_utc(naive, tz_name)

    match = _SHORT_DATE.match(text)
    if match:
        day, month, hour, minute = (int(g) for g in match.groups())
        try:
            naive = datetime(now_local.year, month, day, min(hour, 23), min(minute, 59))
        except ValueError:
            return None
        result = to_utc(naive, tz_name)
        if result < utcnow():
            try:
                result = to_utc(naive.replace(year=now_local.year + 1), tz_name)
            except ValueError:
                return None
        return result
    return None


def friendly_error(error: Exception) -> str:
    """Turn a provider failure into something the business owner can act on."""
    from app.core.exceptions import ConfigurationError, ProviderError, RateLimitError

    if isinstance(error, RateLimitError):
        return texts.AI_RATE_LIMITED
    if isinstance(error, ConfigurationError):
        return texts.AI_NOT_CONFIGURED
    if isinstance(error, ProviderError) and "quota" in str(error).lower():
        return texts.AI_RATE_LIMITED
    return texts.ERROR_GENERIC


def is_command(text: str | None) -> bool:
    return bool(text and text.startswith("/"))
