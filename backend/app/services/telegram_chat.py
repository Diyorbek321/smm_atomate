"""A business's own Telegram bot, answering the people its channel brought in.

:mod:`app.bot` is the platform bot — the admins' workbench, polled, one token
for everybody. This is the other bot: the one a client creates for their own
brand, made admin of their channel, and pointed at
``<PUBLIC_BASE_URL>/telegram/chat/<business_id>/webhook``.

Webhook rather than a poller per business because a poller is a process, and a
process per client is a deployment problem; a webhook is a row and a URL. The
cost is that the two bots must never share a token: setting a webhook on the
platform token silently stops the admin bot's polling. :func:`connect` refuses.

Two kinds of conversation, the same two Instagram has:

* **A DM** — somebody pressed "botga yozing". Answered privately.
* **A comment** — a reply to a channel post inside the linked discussion
  group. Answered in-thread, briefly, because everyone reads it. Only direct
  replies to the post: a side conversation between two people is theirs.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger

log = get_logger(__name__)

#: Telegram's own ceiling on a message; answers are far shorter in practice.
MESSAGE_LIMIT = 4096
#: Only these update kinds reach the webhook — edits and reactions never cost
#: a model call.
ALLOWED_UPDATES = ["message"]


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """One thing a stranger said to the business's bot."""

    kind: str                      # "start" | "message" | "comment"
    chat_id: int
    message_id: int
    user_id: int
    text: str = ""
    username: str = ""
    full_name: str = ""
    #: The channel whose post was commented on; zero for a DM.
    channel_id: int = 0
    channel_username: str = ""

    def to_task(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "chat_id": self.chat_id, "message_id": self.message_id,
            "user_id": self.user_id, "text": self.text, "username": self.username,
            "full_name": self.full_name, "channel_id": self.channel_id,
            "channel_username": self.channel_username,
        }


def webhook_secret(business_id: uuid.UUID | str) -> str:
    """The `secret_token` Telegram echoes back on every delivery.

    Derived rather than stored: nothing to migrate, nothing to leak from the
    database, and it changes with `SECRET_KEY` like everything else signed.
    Hex is within the `[A-Za-z0-9_-]` Telegram accepts.
    """
    message = f"tg-chat:{business_id}".encode()
    return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()


def verify_secret(business_id: uuid.UUID | str, header: str | None) -> bool:
    if not header:
        return False
    return hmac.compare_digest(webhook_secret(business_id), header)


def parse_update(update: dict[str, Any]) -> ChatEvent | None:
    """The update as something worth answering, or None.

    Unknown shapes are skipped rather than raised on: a webhook that keeps
    failing is one Telegram backs off from, losing the messages it could have
    handled.
    """
    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict):
        return None
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    text = str(message.get("text") or message.get("caption") or "").strip()
    if not text or sender.get("is_bot") or not sender.get("id") or not chat.get("id"):
        return None
    # A channel (or an anonymous admin) posting into its own thread.
    if message.get("sender_chat"):
        return None

    common = {
        "chat_id": int(chat["id"]),
        "message_id": int(message.get("message_id") or 0),
        "user_id": int(sender["id"]),
        "text": text,
        "username": str(sender.get("username") or ""),
        "full_name": " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")])),
    }

    if chat.get("type") == "private":
        if text.startswith("/"):
            command = text.split()[0].split("@")[0].lower()
            return ChatEvent(kind="start", **common) if command == "/start" else None
        return ChatEvent(kind="message", **common)

    parent = message.get("reply_to_message") or {}
    channel = parent.get("sender_chat") or {}
    if not parent.get("is_automatic_forward") or channel.get("type") != "channel":
        return None
    if text.startswith("/"):
        return None
    return ChatEvent(
        kind="comment",
        channel_id=int(channel.get("id") or 0),
        channel_username=str(channel.get("username") or ""),
        **common,
    )


def belongs_to_channel(
    event: ChatEvent, *, channel_ref: str | None, discussion_id: str | None
) -> bool:
    """Whether a comment sits under *this* business's channel.

    Anyone can add a bot to a group. Without this check the business pays a
    model call — and speaks in its own name — for every stranger's group the
    bot was dropped into.
    """
    if event.kind != "comment":
        return True
    if discussion_id and str(event.chat_id) == str(discussion_id).strip():
        return True
    ref = (channel_ref or "").strip()
    if not ref:
        return False
    if ref.startswith("@"):
        return bool(event.channel_username) and ref[1:].lower() == event.channel_username.lower()
    return ref == str(event.channel_id)


def message_to_update(message: Any) -> dict[str, Any]:
    """An aiogram message as the raw update the webhook would have received.

    The platform bot polls, so it holds aiogram objects; dumping them by alias
    (``from`` rather than ``from_user``) lets :func:`parse_update` stay the one
    place that decides what is worth answering.
    """
    return {"message": message.model_dump(mode="json", by_alias=True, exclude_none=True)}


def match_business(
    event: ChatEvent, rows: Iterable[tuple[uuid.UUID, str | None, str | None]]
) -> uuid.UUID | None:
    """The business whose channel a comment heard by the platform bot sits under.

    One bot publishes for every business, so it sits in every discussion
    group; ``rows`` is ``(business_id, channel_ref, discussion_id)`` per
    business with Telegram switched on.
    """
    for business_id, channel_ref, discussion_id in rows:
        if belongs_to_channel(event, channel_ref=channel_ref, discussion_id=discussion_id):
            return business_id
    return None


def webhook_url(business_id: uuid.UUID | str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/telegram/chat/{business_id}/webhook"


async def connect(business_id: uuid.UUID, token: str) -> dict[str, Any]:
    """Point the business's bot at this server.

    Refuses the platform token and a non-HTTPS base URL up front, because
    Telegram's own errors for both arrive later and say less.
    """
    if not token:
        raise ConfigurationError("Biznesning Telegram bot tokeni kiritilmagan")
    if token == settings.telegram_bot_token:
        raise ConfigurationError(
            "Bu platformaning admin boti. Chatbot uchun BotFather'da alohida bot oching — "
            "aks holda admin bot ishlashdan to'xtaydi."
        )
    url = webhook_url(business_id)
    if not url.startswith("https://"):
        raise ConfigurationError(f"Telegram faqat HTTPS manzilga yuboradi, PUBLIC_BASE_URL: {url}")

    from app.bot.main import bot_session

    async with bot_session(token) as bot:
        await bot.set_webhook(
            url=url,
            secret_token=webhook_secret(business_id),
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=True,
        )
        me = await bot.get_me()
        info = await bot.get_webhook_info()
    log.info("tg_chatbot_connected", business=str(business_id), bot=me.username)
    return {"bot": me.username, "url": url, "pending": info.pending_update_count,
            "can_read_groups": bool(me.can_read_all_group_messages)}


async def send_reply(token: str, event: ChatEvent, text: str) -> None:
    """Answer in place: a DM in the DM, a comment threaded under the comment."""
    from app.bot.main import bot_session

    async with bot_session(token) as bot:
        await bot.send_message(
            event.chat_id,
            text[:MESSAGE_LIMIT],
            # Model output is plain text; HTML mode would choke on a stray "<".
            parse_mode=None,
            reply_to_message_id=event.message_id if event.kind == "comment" else None,
        )
