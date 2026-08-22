"""Telegram Bot API publisher (channel posts, albums, quizzes, stories)."""

from __future__ import annotations

import json
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import ConfigurationError, PublishError
from app.core.logging import get_logger
from app.services.http import get_client
from app.services.storage import local_media_path
from app.utils.text import TG_CAPTION_LIMIT, TG_MESSAGE_LIMIT, truncate_caption

log = get_logger(__name__)

API_ROOT = "https://api.telegram.org"

#: Telegram poll constraints.
POLL_QUESTION_LIMIT = 300
POLL_OPTION_LIMIT = 100
POLL_MAX_OPTIONS = 10
POLL_EXPLANATION_LIMIT = 200


#: Uploads are metered on the slowest link we have seen in production
#: (~50 KB/s out of Tashkent); budget half of that so a big clip still fits.
UPLOAD_BYTES_PER_SECOND = 25_000
UPLOAD_TIMEOUT_FLOOR = 300.0
UPLOAD_TIMEOUT_CEILING = 900.0


def _upload_timeout(files: dict[str, Path]) -> httpx.Timeout:
    """Scale the read timeout to the payload — a 3 MB clip took 60s live."""
    total = sum(path.stat().st_size for path in files.values() if path.is_file())
    budget = total / UPLOAD_BYTES_PER_SECOND + 60.0
    return httpx.Timeout(min(max(budget, UPLOAD_TIMEOUT_FLOOR), UPLOAD_TIMEOUT_CEILING), connect=15.0)


def _form_values(payload: dict[str, Any]) -> dict[str, str]:
    """Multipart fields must be strings; Telegram expects lowercase booleans."""
    values: dict[str, str] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, bool):
            values[key] = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            values[key] = json.dumps(value, ensure_ascii=False)
        else:
            values[key] = str(value)
    return values


@dataclass(slots=True)
class TelegramResult:
    message_id: str
    chat_id: str
    raw: dict[str, Any]


class TelegramPublisher:
    """Stateless helper — one instance per bot token."""

    def __init__(self, bot_token: str | None = None) -> None:
        self.token = bot_token or settings.telegram_bot_token
        if not self.token:
            raise ConfigurationError("Telegram bot token is missing")

    async def _call(
        self, method: str, payload: dict[str, Any], files: dict[str, Path] | None = None
    ) -> dict[str, Any]:
        """POST to the Bot API — JSON normally, multipart when uploading files."""
        client = await get_client("telegram", timeout=90)
        url = f"{API_ROOT}/bot{self.token}/{method}"
        try:
            if files:
                with ExitStack() as stack:
                    handles = {
                        field: (path.name, stack.enter_context(path.open("rb")))
                        for field, path in files.items()
                    }
                    # Pooled clients keep the timeout they were built with, so
                    # long uploads must override it on the request itself.
                    response = await client.post(
                        url,
                        data=_form_values(payload),
                        files=handles,
                        timeout=_upload_timeout(files),
                    )
            else:
                response = await client.post(url, json=payload)
        except OSError as exc:
            raise PublishError("telegram", f"cannot read media: {exc}", retryable=False) from exc
        except Exception as exc:
            raise PublishError("telegram", f"network error: {exc}", retryable=True) from exc

        try:
            data = response.json()
        except Exception:
            raise PublishError(
                "telegram", f"invalid response (HTTP {response.status_code})", retryable=True
            ) from None

        if not data.get("ok"):
            description = str(data.get("description", "unknown error"))
            code = int(data.get("error_code", response.status_code))
            retry_after = (data.get("parameters") or {}).get("retry_after")
            # 429 / 5xx are transient; 400 usually means bad content -> no retry.
            retryable = code in (420, 429, 500, 502, 503) or bool(retry_after)
            raise PublishError(
                "telegram",
                f"{method} failed [{code}]: {description}",
                retryable=retryable,
                details={"method": method, "retry_after": retry_after, "response": data},
            )
        return data.get("result") or {}

    # ------------------------------------------------------------------ #
    # Public methods
    # ------------------------------------------------------------------ #
    async def send_message(self, chat_id: str, text: str, *, parse_mode: str = "HTML") -> TelegramResult:
        result = await self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": truncate_caption(text, TG_MESSAGE_LIMIT),
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
        )
        return TelegramResult(str(result.get("message_id", "")), str(chat_id), result)

    def _split_caption(self, caption: str) -> tuple[str, str]:
        """Telegram caps captions; the tail is sent as a reply instead."""
        text = caption or ""
        if len(text) <= TG_CAPTION_LIMIT:
            return text, ""
        head = truncate_caption(text, TG_CAPTION_LIMIT)
        return head, text[len(head.rstrip("\u2026")) :].strip()

    async def _send_media(
        self,
        method: str,
        field: str,
        chat_id: str,
        media_url: str,
        caption: str,
        parse_mode: str,
        extra: dict[str, Any] | None = None,
    ) -> TelegramResult:
        """Send one photo/video, uploading the bytes when the file is ours."""
        caption_text, overflow = self._split_caption(caption)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": caption_text,
            "parse_mode": parse_mode,
            **(extra or {}),
        }

        local = local_media_path(media_url)
        if local is not None:
            result = await self._call(method, payload, files={field: local})
        else:
            payload[field] = media_url
            result = await self._call(method, payload)

        message_id = str(result.get("message_id", ""))
        if overflow:
            await self._call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": truncate_caption(overflow, TG_MESSAGE_LIMIT),
                    "parse_mode": parse_mode,
                    "reply_to_message_id": result.get("message_id"),
                    "disable_web_page_preview": True,
                },
            )
        return TelegramResult(message_id, str(chat_id), result)

    async def send_photo(
        self, chat_id: str, photo_url: str, caption: str = "", *, parse_mode: str = "HTML"
    ) -> TelegramResult:
        return await self._send_media("sendPhoto", "photo", chat_id, photo_url, caption, parse_mode)

    async def send_video(
        self, chat_id: str, video_url: str, caption: str = "", *, parse_mode: str = "HTML"
    ) -> TelegramResult:
        return await self._send_media(
            "sendVideo",
            "video",
            chat_id,
            video_url,
            caption,
            parse_mode,
            extra={"supports_streaming": True},
        )

    async def send_album(
        self, chat_id: str, photo_urls: list[str], caption: str = "", *, parse_mode: str = "HTML"
    ) -> TelegramResult:
        """Carousel → Telegram media group (max 10 photos, caption on the first)."""
        urls = [u for u in photo_urls if u][:10]
        if not urls:
            raise PublishError("telegram", "album requires at least one photo", retryable=False)
        if len(urls) == 1:
            return await self.send_photo(chat_id, urls[0], caption, parse_mode=parse_mode)

        media = []
        files: dict[str, Path] = {}
        for index, url in enumerate(urls):
            local = local_media_path(url)
            if local is not None:
                field = f"file{index}"
                files[field] = local
                source = f"attach://{field}"
            else:
                source = url
            entry: dict[str, Any] = {"type": "photo", "media": source}
            if index == 0 and caption:
                entry["caption"] = truncate_caption(caption, TG_CAPTION_LIMIT)
                entry["parse_mode"] = parse_mode
            media.append(entry)

        result = await self._call(
            "sendMediaGroup",
            {"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)},
            files=files or None,
        )
        first = result[0] if isinstance(result, list) and result else {}
        return TelegramResult(str(first.get("message_id", "")), str(chat_id), {"messages": result})

    async def send_quiz(
        self,
        chat_id: str,
        question: str,
        answers: list[str],
        *,
        correct_option_id: int = 0,
        explanation: str = "",
        is_anonymous: bool = True,
    ) -> TelegramResult:
        options = [truncate_caption(str(a), POLL_OPTION_LIMIT) for a in answers if str(a).strip()][
            :POLL_MAX_OPTIONS
        ]
        if len(options) < 2:
            raise PublishError("telegram", "a quiz needs at least 2 options", retryable=False)
        correct = correct_option_id if 0 <= correct_option_id < len(options) else 0

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "question": truncate_caption(question, POLL_QUESTION_LIMIT),
            "options": json.dumps(options, ensure_ascii=False),
            "type": "quiz",
            "correct_option_id": correct,
            "is_anonymous": is_anonymous,
        }
        if explanation:
            payload["explanation"] = truncate_caption(explanation, POLL_EXPLANATION_LIMIT)
            payload["explanation_parse_mode"] = "HTML"

        result = await self._call("sendPoll", payload)
        return TelegramResult(str(result.get("message_id", "")), str(chat_id), result)

    async def get_me(self) -> dict[str, Any]:
        """Credential validation helper used by the API layer."""
        return await self._call("getMe", {})

    async def check_channel(self, chat_id: str) -> dict[str, Any]:
        return await self._call("getChat", {"chat_id": chat_id})
