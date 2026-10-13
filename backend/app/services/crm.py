"""The client's CRM: where leads go, and what the bot may quote.

Shanghai School runs on a CRM whose public site posts its enrolment form to
``<api_base>/register``. A lead the bot caught goes to that same endpoint, so
the sales team works one inbox instead of two. The same public API serves the
course list and the branches — the most authoritative facts the bot can quote,
because they are what the school itself publishes.

Configured per business in ``Business.settings["crm"]``::

    {"api_base": "https://shanghai-edu.uz/api/public", "center_id": 4, "push": true}

``push`` is off unless set: turning it on also sends every lead already in the
database, and that is a decision about somebody's live CRM, not a default.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

#: The catalog changes when somebody edits the site, not per message.
CATALOG_TTL_SEC = 600
#: How each source reads in the CRM, where the team sees it next to site forms.
SOURCE_LABELS = {
    "telegram_message": "Telegram chatbot (DM)",
    "telegram_comment": "Telegram kanal kommenti",
    "instagram_message": "Instagram DM",
    "instagram_comment": "Instagram kommenti",
    "bot": "Telegram bot",
}
_APOSTROPHES = str.maketrans({c: "'" for c in "ʻʼ‘’`´"})

_catalog_cache: dict[tuple[str, int | None], tuple[float, Catalog]] = {}


class CrmError(Exception):
    """The CRM did not take the lead. Retryable: the lead stays unsynced."""


@dataclass(frozen=True, slots=True)
class CrmConfig:
    api_base: str
    center_id: int | None = None
    push: bool = False

    @property
    def register_url(self) -> str:
        return f"{self.api_base}/register"

    def url(self, path: str) -> str:
        query = f"?center_id={self.center_id}" if self.center_id else ""
        return f"{self.api_base}/{path.lstrip('/')}{query}"


@dataclass(frozen=True, slots=True)
class Catalog:
    courses: list[dict[str, Any]]
    branches: list[dict[str, Any]]


def crm_config(business: Any) -> CrmConfig | None:
    """The business's CRM settings, or None when it has none worth using.

    Plain HTTP is refused: a lead is a name and a phone number.
    """
    raw = ((getattr(business, "settings", None) or {}).get("crm")) or {}
    api_base = str(raw.get("api_base") or "").strip().rstrip("/")
    if not api_base.startswith("https://"):
        return None
    center = raw.get("center_id")
    return CrmConfig(
        api_base=api_base,
        center_id=int(center) if center not in (None, "") else None,
        push=bool(raw.get("push", False)),
    )


def _normalise(text: str) -> str:
    text = (text or "").lower().translate(_APOSTROPHES)
    return re.sub(r"[^\w' ]+", " ", text)


def _active(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in courses if c.get("is_active", True) and c.get("name")]


def match_course(text: str, courses: list[dict[str, Any]]) -> int | None:
    """The one course this message is clearly about, or None.

    Matched on the first word of the course name ("xitoy", "python") because
    people write "xitoy tiliga", not the catalog title. Two different subjects
    in one message is no answer at all — guessing would file the lead under the
    wrong teacher.
    """
    words = _normalise(text).split()
    if not words:
        return None
    flat = " ".join(words)
    hits: dict[str, list[dict[str, Any]]] = {}
    for course in _active(courses):
        name = _normalise(course["name"]).split()
        stem = name[0] if name else ""
        if len(stem) < 4:
            continue
        if any(word.startswith(stem) for word in words):
            hits.setdefault(stem, []).append(course)
    if len(hits) != 1:
        return None
    candidates = next(iter(hits.values()))

    def rank(course: dict[str, Any]) -> tuple[int, int, int]:
        name = " ".join(_normalise(course["name"]).split())
        return (
            name in flat,                   # the whole title was written
            "ochiq" not in name,            # the regular course over its open lesson
            -int(course.get("position") or course.get("id") or 0),
        )

    return int(max(candidates, key=rank)["id"])


def _phone(raw: str) -> str:
    """+998XXXXXXXXX when it parses — a Telegram contact arrives without the plus."""
    from app.tasks.instagram import find_phone

    return find_phone(raw) or raw.strip()


def build_payload(lead: Any, cfg: CrmConfig, course_id: int | None) -> dict[str, Any]:
    """The same shape the site's own enrolment form sends."""
    source = SOURCE_LABELS.get(lead.source, lead.source)
    message = f"Manba: {source}"
    if lead.username:
        message += f" · {lead.username}"
    if lead.interest:
        message += f"\nSavol: {lead.interest[:800]}"
    payload: dict[str, Any] = {
        "name": (lead.full_name or lead.username or "Chatbot mijoz")[:120],
        "phone": _phone(lead.phone),
        "message": message,
    }
    if cfg.center_id:
        payload["center_id"] = cfg.center_id
    if course_id:
        payload["course_interest"] = course_id
    return payload


async def push_lead(
    lead: Any,
    cfg: CrmConfig,
    courses: list[dict[str, Any]],
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Send one lead. Raises :class:`CrmError` unless the CRM accepted it."""
    if not lead.phone:
        raise CrmError("lead has no phone; the CRM form requires one")
    payload = build_payload(lead, cfg, match_course(lead.interest, courses))
    if client is None:
        from app.services.http import get_client

        client = await get_client("crm", timeout=30)
    try:
        response = await client.post(cfg.register_url, json=payload)
    except httpx.HTTPError as exc:
        raise CrmError(f"network: {exc}") from exc
    if response.status_code >= 400:
        raise CrmError(f"HTTP {response.status_code}: {response.text[:200]}")
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and body.get("success") is False:
        raise CrmError(f"rejected: {str(body)[:200]}")
    log.info("crm_lead_pushed", lead=str(lead.id), course=payload.get("course_interest"))


async def fetch_catalog(cfg: CrmConfig) -> Catalog:
    """Courses and branches from the public API, cached for a few minutes.

    A failure returns an empty catalog rather than raising: the bot still
    answers from its knowledge base, it just has less to quote.
    """
    key = (cfg.api_base, cfg.center_id)
    cached = _catalog_cache.get(key)
    if cached and time.monotonic() - cached[0] < CATALOG_TTL_SEC:
        return cached[1]

    from app.services.http import get_client

    client = await get_client("crm", timeout=30)
    parts: dict[str, list[dict[str, Any]]] = {}
    for path in ("courses", "branches"):
        try:
            response = await client.get(cfg.url(path))
            response.raise_for_status()
            data = response.json()
            parts[path] = list(data.get("data") or []) if isinstance(data, dict) else []
        except Exception as exc:
            log.warning("crm_catalog_failed", path=path, error=str(exc)[:200])
            parts[path] = []
    catalog = Catalog(courses=parts["courses"], branches=parts["branches"])
    if catalog.courses or catalog.branches:
        _catalog_cache[key] = (time.monotonic(), catalog)
    return catalog


def _is_template(branch: dict[str, Any]) -> bool:
    """An address that only repeats the branch's own name was never filled in."""
    name = _normalise(str(branch.get("name") or "")).strip()
    return bool(name) and name in _normalise(str(branch.get("address") or ""))


def catalog_context(catalog: Catalog) -> str:
    """The catalog as a prompt block, with every missing fact said out loud.

    "narx: saytda yo'q" is there on purpose. Left blank, a missing price is
    one the model fills in from the neighbouring line.
    """
    lines: list[str] = []
    courses = _active(catalog.courses)
    if courses:
        lines.append("Kurslar:")
        for course in courses:
            facts = []
            duration = str(course.get("duration") or "").strip()
            if duration and duration != "—":
                facts.append(f"davomiyligi {duration}")
            facts.append(str(course["intensity"]) if course.get("intensity")
                         else "haftalik soat: saytda yo'q")
            facts.append(f"narx: {course['price']}" if course.get("price") else "narx: saytda yo'q")
            lines.append(f"- {course['name']}: " + "; ".join(facts))
    branches = [b for b in catalog.branches if b.get("is_active", True)]
    if branches:
        lines.append("Filiallar:")
        for branch in branches:
            facts = []
            if branch.get("address") and not _is_template(branch):
                facts.append(str(branch["address"]))
            else:
                facts.append("manzil: saytda yo'q")
            if branch.get("phone"):
                facts.append(f"tel {branch['phone']}")
            if branch.get("working_hours"):
                facts.append(str(branch["working_hours"]))
            lines.append(f"- {branch.get('name', 'Filial')}: " + "; ".join(facts))
    if not lines:
        return ""
    return "SAYTDAGI RASMIY MA'LUMOT (eng ishonchli manba):\n" + "\n".join(lines)


async def catalog_context_for(business: Any) -> str:
    cfg = crm_config(business)
    if cfg is None:
        return ""
    return catalog_context(await fetch_catalog(cfg))
