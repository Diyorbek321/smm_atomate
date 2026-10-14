"""Connect a client's Telegram channel from the dashboard.

The admin gives the channel and makes the platform bot an admin of it and of
its discussion group; Telegram is asked for the rest. ``getChat`` on a channel
returns ``linked_chat_id`` — the discussion group — so nobody has to dig a
``-100…`` id out of a web client.

Each requirement is a separate :class:`Step`, so the dashboard can say exactly
which one is missing. Publishing needs the channel steps; answering comments
also needs the group. A channel without comments is still worth connecting, so
the two outcomes are reported apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.exceptions import PublishError

_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_LINK = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/([^/?#\s]+)", re.IGNORECASE)
_NUMERIC = re.compile(r"^-100\d+$")


class BotApi(Protocol):
    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class Step:
    key: str
    ok: bool
    message: str


@dataclass(frozen=True, slots=True)
class ConnectResult:
    steps: tuple[Step, ...]
    channel_id: str = ""
    username: str = ""
    title: str = ""
    discussion_id: str = ""
    discussion_title: str = ""
    comments_ok: bool = False
    ok: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ok", bool(self.channel_id))


def normalise_channel(raw: str) -> str:
    """``@name`` or ``-100…`` from whatever was pasted; ``""`` when it is neither."""
    text = (raw or "").strip()
    if _NUMERIC.match(text):
        return text
    link = _LINK.match(text)
    if link:
        text = link.group(1)
    elif "/" in text or " " in text:
        return ""
    name = text.removeprefix("@")
    return f"@{name}" if _USERNAME.match(name) else ""


def _reason(exc: Exception) -> str:
    text = str(exc)
    return text.split(": ", 1)[-1][:200] if isinstance(exc, PublishError) else text[:200]


async def _member(api: BotApi, chat_id: int | str, bot_id: int) -> dict[str, Any] | None:
    try:
        return await api._call("getChatMember", {"chat_id": chat_id, "user_id": bot_id})
    except PublishError:
        return None


async def check_channel(api: BotApi, raw_channel: str, *, bot_id: int) -> ConnectResult:
    """Every requirement for publishing and answering comments, checked live."""
    ref = normalise_channel(raw_channel)
    if not ref:
        return ConnectResult(steps=(Step(
            "channel", False, "Not a channel: use @username, a t.me link or a -100… id."),))

    try:
        chat = await api._call("getChat", {"chat_id": ref})
    except PublishError as exc:
        return ConnectResult(steps=(Step(
            "channel", False, f"Telegram cannot see {ref}: {_reason(exc)}. "
            "Is the bot added to the channel?"),))
    if chat.get("type") != "channel":
        return ConnectResult(steps=(Step(
            "channel", False, f"{ref} is a {chat.get('type', 'chat')}, not a channel."),))

    channel_id = int(chat["id"])
    title = str(chat.get("title") or ref)
    steps = [Step("channel", True, f"Channel found: {title}")]

    member = await _member(api, channel_id, bot_id)
    if not member or member.get("status") not in ("administrator", "creator"):
        steps.append(Step("channel_admin", False, "Make the bot an admin of the channel."))
        return ConnectResult(steps=tuple(steps), title=title)
    if member.get("status") == "administrator" and not member.get("can_post_messages"):
        steps.append(Step("channel_admin", False,
                          "The bot is an admin but may not post: enable \"Post messages\"."))
        return ConnectResult(steps=tuple(steps), title=title)
    steps.append(Step("channel_admin", True, "The bot can post in the channel."))

    common = {"channel_id": str(channel_id), "title": title,
              "username": f"@{chat['username']}" if chat.get("username") else ""}
    linked = chat.get("linked_chat_id")
    if not linked:
        steps.append(Step("discussion", False,
                          "The channel has no discussion group, so there are no comments to answer. "
                          "Link one in the channel settings → Discussion."))
        return ConnectResult(steps=tuple(steps), **common)
    steps.append(Step("discussion", True, "Discussion group found."))

    member = await _member(api, linked, bot_id)
    if not member or member.get("status") not in ("administrator", "creator"):
        steps.append(Step("discussion_admin", False,
                          "Make the bot an admin of the discussion group — otherwise it cannot "
                          "read the comments."))
        return ConnectResult(steps=tuple(steps), **common)
    steps.append(Step("discussion_admin", True, "The bot can read and answer comments."))

    return ConnectResult(steps=tuple(steps), discussion_id=str(linked), comments_ok=True, **common)
