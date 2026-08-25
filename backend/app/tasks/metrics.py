"""How many people actually saw it.

The Bot API gives reactions and stops there — no view count, not for our own
channel, not ever. That left this system reasoning about what worked from a
signal only a handful of people ever produce: somebody has to *press* something
before a post exists in the numbers at all.

Telegram's public preview page has the view count the whole time. It is the
same page :mod:`app.services.telegram_scout` reads for competitors, and it does
not care that the channel is ours. So the reach we could not get through the
API comes back through the front door.

Only public channels. A private channel has no preview page, and a numeric
``tg_channel_id`` cannot be turned into one — those businesses keep the
reaction-only picture they had.
"""

from __future__ import annotations

import re
from typing import Any

from celery import shared_task

from app.core.logging import get_logger
from app.db.session import session_scope
from app.repositories.business import BusinessRepository, CredentialsRepository
from app.repositories.content import ContentItemRepository
from app.services.telegram_scout import fetch_channel, own_channel_handle
from app.tasks.celery_app import celery_app  # noqa: F401 - registers the app
from app.tasks.runner import run_async
from app.utils.dates import utcnow

log = get_logger(__name__)

#: `data-post` is `<channel>/<id>`, sometimes with an album suffix (`?single`).
_ID_RE = re.compile(r"(\d+)(?:\?.*)?$")


def message_id_of(post: Any) -> str | None:
    """The Telegram message id out of a preview post's `data-post` value."""
    raw = str(getattr(post, "post_id", "") or "").strip()
    if not raw:
        return None
    match = _ID_RE.search(raw.rsplit("/", 1)[-1])
    return match.group(1) if match else None


def views_by_message(snapshot: Any) -> dict[str, int]:
    """`{message id: views}` for everything on the page that carries a count.

    A zero is dropped rather than stored: Telegram omits the counter on posts
    too new to have one, and writing 0 would tell the analyst that nobody
    looked — the opposite of "not counted yet".
    """
    mapping: dict[str, int] = {}
    for post in getattr(snapshot, "posts", []) or []:
        views = int(getattr(post, "views", 0) or 0)
        if views <= 0:
            continue
        message_id = message_id_of(post)
        if message_id:
            mapping[message_id] = views
    return mapping


def apply_views(item: Any, views: int) -> bool:
    """Record the count on the item. True when something actually changed.

    Views only climb, so a smaller reading is a rounding artefact rather than
    news — Telegram serves `1.2K` once a post passes a thousand, and parsing
    that back gives 1200 for anything from 1150 to 1249. Keeping the larger
    number stops a post's measured reach from going backwards.
    """
    metrics = dict(item.metrics or {})
    previous = int(metrics.get("views") or 0)
    if views <= previous:
        return False

    metrics["views"] = views
    metrics["views_at"] = utcnow().isoformat()
    # Reassigned rather than mutated: SQLAlchemy does not see an in-place edit
    # of a JSONB dict, and the reaction handler writes to this same column.
    item.metrics = metrics
    return True


async def collect_views_for(session: Any, business: Any) -> dict[str, Any]:
    """Read one business's public channel and record what it reports."""
    credentials = await CredentialsRepository(session).for_business(business.id)
    handle = own_channel_handle(credentials)
    if not handle:
        return {"business": business.name, "skipped": "kanal ochiq emas"}

    snapshot = await fetch_channel(handle)
    if snapshot is None:
        return {"business": business.name, "skipped": "sahifa o'qilmadi"}

    seen = views_by_message(snapshot)
    if not seen:
        return {"business": business.name, "skipped": "ko'rish soni yo'q"}

    items = await ContentItemRepository(session).by_telegram_messages(
        business.id, list(seen)
    )
    updated = sum(1 for item in items if apply_views(item, seen[str(item.tg_message_id)]))
    await session.flush()

    log.info(
        "views_collected",
        business=str(business.id),
        handle=handle,
        on_page=len(seen),
        matched=len(items),
        updated=updated,
    )
    return {
        "business": business.name,
        "handle": handle,
        "on_page": len(seen),
        "matched": len(items),
        "updated": updated,
    }


async def run_view_collection() -> dict[str, Any]:
    """Every business with a public channel, one page each."""
    results: list[dict[str, Any]] = []
    async with session_scope() as session:
        for business in await BusinessRepository(session).list_active():
            try:
                results.append(await collect_views_for(session, business))
            except Exception as exc:      # one bad channel must not stop the rest
                log.warning(
                    "view_collection_failed",
                    business=str(business.id),
                    error=str(exc)[:200],
                )
                results.append({"business": business.name, "error": str(exc)[:120]})
    return {"businesses": len(results), "results": results}


@shared_task(name="app.tasks.metrics.collect_channel_views")
def collect_channel_views() -> dict[str, Any]:
    """Scheduled reach collection.

    Runs a few times a day rather than hourly: a post's view count climbs
    fastest in its first hours and then flattens, and the page only carries the
    most recent posts either way.
    """
    return run_async(run_view_collection())
