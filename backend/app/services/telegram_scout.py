"""Public Telegram channels, read the way a browser reads them.

Every agent in this system reasons from what the client told us. Nothing has
ever looked outward, so the strategist plans in a room with no windows: it
cannot see that three competitors ran the same offer last week, or that the
one format earning replies in this niche is a thirty-second phone video.

Telegram publishes a preview page for every public channel at ``t.me/s/<name>``
— the same HTML a browser gets, no key, no account. For local Uzbek businesses
that is the whole competitive picture, because the competitors are on Telegram
and their channels are public.

It also hands over a number our own pipeline cannot get: **views**. The Bot API
exposes reactions and nothing else, so a client's own public channel read this
way finally answers "how many people saw it" — see :func:`own_channel_handle`.

Deliberately LLM-free. This module fetches, parses and *ranks*; deciding what
the ranking means is :class:`app.agents.scout.ScoutAgent`'s job.
"""

from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

from app.core.logging import get_logger
from app.services.http import request_with_retry

log = get_logger(__name__)

PREVIEW_URL = "https://t.me/s/{handle}"

#: Telegram handles: 5-32 chars, letters/digits/underscore, must start a letter.
_HANDLE_RE = re.compile(r"(?:^|t\.me/|@)(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})/?$")

_POST_SPLIT_RE = re.compile(r'<div class="tgme_widget_message_wrap')
_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.DOTALL
)
_VIEWS_RE = re.compile(r'<span class="tgme_widget_message_views">([^<]+)</span>')
_DATE_RE = re.compile(r'<time datetime="([^"]+)"')
_POST_ID_RE = re.compile(r'data-post="([^"]+)"')
_SUBS_RE = re.compile(
    r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">subscribers</span>'
)
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)

#: A post carrying this many times its channel's median views is the signal we
#: came for. Below it, the number says more about the channel than the post.
DEFAULT_MIN_LIFT = 1.5
#: Politeness: these are public pages, but they are not an API.
FETCH_DELAY_SECONDS = 1.0


def extract_handle(value: str) -> str | None:
    """Pull a channel handle out of whatever the owner typed.

    Onboarding asks for competitors and gets back a mix: ``@najottalim``, a
    ``t.me`` link, or just a name. A name cannot be resolved to a channel
    without a search API we do not have, so it returns None and the caller
    reports it as something to ask the owner for.
    """
    text = (value or "").strip().rstrip("/")
    if not text:
        return None
    text = text.removeprefix("https://").removeprefix("http://")
    match = _HANDLE_RE.search(text)
    return match.group(1) if match else None


def parse_count(value: str) -> int:
    """``"14.7M"`` → 14700000. Telegram abbreviates; comparisons need integers."""
    text = (value or "").strip().replace(",", "").replace(" ", "")
    if not text:
        return 0
    multiplier = 1
    if text[-1] in "KkKМмMm":
        suffix = text[-1].lower()
        multiplier = 1_000_000 if suffix in "mм" else 1_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def _clean_text(fragment: str) -> str:
    """The post's words, with the markup and the emoji sprites taken out."""
    text = _BR_RE.sub("\n", fragment)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    # Telegram's markup is full of &nbsp;. Left as U+00A0 it survives into the
    # prompt and the word count, where it is a space that does not behave.
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


@dataclass(slots=True)
class ScoutPost:
    """One published post, as the public preview shows it."""

    handle: str
    post_id: str = ""
    text: str = ""
    views: int = 0
    posted_at: datetime | None = None
    has_video: bool = False
    has_photo: bool = False
    #: Views relative to this channel's median. Filled by `ChannelSnapshot`.
    lift: float = 0.0

    @property
    def media(self) -> str:
        if self.has_video:
            return "video"
        if self.has_photo:
            return "rasm"
        return "matn"

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass(slots=True)
class ChannelSnapshot:
    """What one competitor published lately, and how it landed."""

    handle: str
    subscribers: int = 0
    posts: list[ScoutPost] = field(default_factory=list)

    @property
    def median_views(self) -> int:
        measured = [p.views for p in self.posts if p.views > 0]
        return int(median(measured)) if measured else 0

    @property
    def is_usable(self) -> bool:
        """Two posts cannot establish a median, so lift would be meaningless."""
        return len([p for p in self.posts if p.views > 0]) >= 3

    def rank(self) -> None:
        """Score every post against this channel's own median.

        The whole point of doing it per channel: 400 views is a hit on a
        500-subscriber channel and a rounding error on a national one. Compared
        raw, the biggest channel wins every week and the ranking says nothing.
        """
        baseline = self.median_views
        for post in self.posts:
            post.lift = round(post.views / baseline, 2) if baseline else 0.0

    def outperformers(self, *, min_lift: float = DEFAULT_MIN_LIFT, limit: int = 5) -> list[ScoutPost]:
        ranked = sorted(
            (p for p in self.posts if p.lift >= min_lift and p.text),
            key=lambda p: p.lift,
            reverse=True,
        )
        return ranked[:limit]


def parse_channel(page: str, handle: str) -> ChannelSnapshot:
    """Turn the preview page into a ranked snapshot. Pure — no network."""
    snapshot = ChannelSnapshot(handle=handle)

    subs = _SUBS_RE.search(page)
    if subs:
        snapshot.subscribers = parse_count(subs.group(1))

    for block in _POST_SPLIT_RE.split(page)[1:]:
        text_match = _TEXT_RE.search(block)
        views_match = _VIEWS_RE.search(block)
        # A post with neither words nor a view count tells us nothing; service
        # messages ("X joined the channel") come through looking exactly so.
        if not text_match and not views_match:
            continue

        posted_at = None
        date_match = _DATE_RE.search(block)
        if date_match:
            try:
                posted_at = datetime.fromisoformat(date_match.group(1))
            except ValueError:
                posted_at = None

        post_id = _POST_ID_RE.search(block)
        snapshot.posts.append(
            ScoutPost(
                handle=handle,
                post_id=post_id.group(1) if post_id else "",
                text=_clean_text(text_match.group(1)) if text_match else "",
                views=parse_count(views_match.group(1)) if views_match else 0,
                posted_at=posted_at,
                has_video="tgme_widget_message_video" in block,
                has_photo="tgme_widget_message_photo" in block,
            )
        )

    snapshot.rank()
    return snapshot


async def fetch_channel(handle: str) -> ChannelSnapshot | None:
    """Read one public channel. None when it is private, gone, or unreachable."""
    try:
        response = await request_with_retry(
            "telegram-preview",
            "GET",
            PREVIEW_URL.format(handle=handle),
            client_name="scout",
            attempts=2,
        )
    except Exception as exc:
        log.warning("scout_fetch_failed", handle=handle, error=str(exc)[:160])
        return None

    snapshot = parse_channel(response.text, handle)
    if not snapshot.posts:
        # A private channel still returns 200, with a "preview unavailable" page.
        log.info("scout_no_posts", handle=handle)
        return None
    return snapshot


async def scout(handles: list[str], *, limit: int = 5) -> list[ChannelSnapshot]:
    """Read up to `limit` channels, one at a time.

    Sequential with a pause on purpose. These are public pages served for
    browsers, not an API with a published budget, and a weekly planning run has
    no deadline worth hurrying them for.
    """
    seen: set[str] = set()
    snapshots: list[ChannelSnapshot] = []

    for raw in handles:
        if len(snapshots) >= limit:
            break
        handle = extract_handle(raw)
        if not handle or handle.lower() in seen:
            continue
        seen.add(handle.lower())

        if snapshots:
            await asyncio.sleep(FETCH_DELAY_SECONDS)
        snapshot = await fetch_channel(handle)
        if snapshot is not None:
            snapshots.append(snapshot)

    log.info("scout_read", channels=len(snapshots), requested=len(handles))
    return snapshots


def unresolved(handles: list[str]) -> list[str]:
    """The competitor entries that are names, not channels.

    Surfaced rather than dropped: "Najot Ta'lim" is useful intelligence the
    moment somebody asks the owner for the channel link, and useless until then.
    """
    return [h.strip() for h in handles if h.strip() and extract_handle(h) is None]


def own_channel_handle(credentials: Any) -> str | None:
    """This business's own channel, when it is public and addressable.

    ``tg_channel_id`` holds either ``@name`` or a numeric id. Only the former
    has a preview page — and reading it is the only way this system ever learns
    how many people saw its own work.
    """
    value = getattr(credentials, "tg_channel_id", None)
    if not value or str(value).lstrip("-").isdigit():
        return None
    return extract_handle(str(value))
