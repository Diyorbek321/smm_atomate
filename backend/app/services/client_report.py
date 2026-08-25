"""The month, written for the person paying for it.

:mod:`app.services.analytics` counts what this system produced — items, cost,
queue depth. That is an operator's view, and it answers a question the client
never asked. They asked whether anyone came.

So this report leads with leads, states plainly what could not be measured
instead of quietly omitting it, and names what the client themselves did not
supply. A report that only contains good news teaches the reader to stop
believing the good news.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business import Business
from app.models.content_item import ContentItem
from app.models.enums import ContentItemStatus, ContentType
from app.repositories.content import ContentItemRepository
from app.repositories.lead import LeadRepository
from app.utils.dates import to_local

#: Human labels for the types a client recognises.
TYPE_LABELS: dict[str, str] = {
    ContentType.FEED_POST.value: "post",
    ContentType.CAROUSEL.value: "karusel",
    ContentType.STORY.value: "story",
    ContentType.TELEGRAM_QUIZ.value: "so'rovnoma",
    ContentType.REELS_SCRIPT.value: "reels",
    ContentType.VIDEO_POST.value: "video",
}

MONTH_NAMES = (
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
)


@dataclass(frozen=True, slots=True)
class TopPost:
    headline: str
    content_type: str
    reactions: int | None
    published_on: date


@dataclass(slots=True)
class ClientReport:
    business: str
    period_start: date
    period_end: date

    published_total: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    top_posts: list[TopPost] = field(default_factory=list)

    leads_total: int = 0
    leads_new: int = 0
    leads_contacted: int = 0

    avg_quality: float = 0.0
    scheduled_next: int = 0

    #: Numbers we do not have, said out loud.
    unmeasured: list[str] = field(default_factory=list)
    #: Things the client owes us, and what it cost them.
    gaps: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{MONTH_NAMES[self.period_start.month - 1]} {self.period_start.year}"


def month_bounds(when: date | None = None) -> tuple[datetime, datetime]:
    """UTC bounds of the month `when` falls in, defaulting to last month.

    Last month rather than this one: a report is written about a period that
    has finished, and running it on the 1st is the natural cadence.
    """
    today = when or (date.today().replace(day=1) - timedelta(days=1))
    start = datetime(today.year, today.month, 1)
    end = (
        datetime(today.year + 1, 1, 1)
        if today.month == 12
        else datetime(today.year, today.month + 1, 1)
    ) - timedelta(microseconds=1)
    return start, end


async def build_report(
    session: AsyncSession, business: Business, when: date | None = None
) -> ClientReport:
    start, end = month_bounds(when)
    items = ContentItemRepository(session)

    published = list(await items.published_between(business.id, start, end))
    report = ClientReport(
        business=business.name,
        period_start=start.date(),
        period_end=end.date(),
        published_total=len(published),
    )

    for item in published:
        key = TYPE_LABELS.get(item.content_type.value, item.content_type.value)
        report.by_type[key] = report.by_type.get(key, 0) + 1

    report.top_posts = _rank(published, business.timezone)

    if published:
        scored = [i.quality_score for i in published if i.quality_score]
        report.avg_quality = round(sum(scored) / len(scored), 1) if scored else 0.0

    leads = await LeadRepository(session).counts_between(business.id, start, end)
    report.leads_total = leads.get("total", 0)
    report.leads_new = leads.get("new", 0)
    report.leads_contacted = leads.get("contacted", 0)

    report.scheduled_next = await items.count_between(
        end,
        end + timedelta(days=31),
        statuses=[ContentItemStatus.APPROVED, ContentItemStatus.PENDING_REVIEW],
        business_id=business.id,
    )

    report.unmeasured = _unmeasured(business, published)
    report.gaps = _gaps(business, published)
    return report


def _rank(published: list[ContentItem], tz: str, limit: int = 3) -> list[TopPost]:
    """Best posts by reactions, newest first when nothing was measured.

    Telegram gives reaction counts; Instagram gives nothing without a
    connected Insights token. Sorting unmeasured items by date rather than
    dropping them keeps the section honest instead of empty.
    """
    def reactions(item: ContentItem) -> int | None:
        value = (item.metrics or {}).get("reactions")
        return int(value) if isinstance(value, int) else None

    measured = [i for i in published if reactions(i) is not None]
    pool = measured or published
    pool = sorted(
        pool,
        key=lambda i: (reactions(i) or 0, i.published_at or datetime.min),
        reverse=True,
    )
    return [
        TopPost(
            headline=(item.headline or item.topic or "—")[:80],
            content_type=TYPE_LABELS.get(item.content_type.value, item.content_type.value),
            reactions=reactions(item),
            published_on=to_local(item.published_at, tz).date()
            if item.published_at
            else date.today(),
        )
        for item in pool[:limit]
    ]


def _unmeasured(business: Business, published: list[ContentItem]) -> list[str]:
    notes: list[str] = []
    if any(i.ig_media_id for i in published):
        notes.append(
            "Instagram qamrovi va saqlashlar — IG Insights ulanmagan, raqam yo'q."
        )
    if not any((i.metrics or {}).get("reactions") is not None for i in published):
        notes.append("Telegram reaksiyalari hali yig'ilmagan.")
    notes.append(
        "Lid qaysi postdan kelgani bog'lanmagan — hozircha faqat umumiy son bor."
    )
    return notes


def _gaps(business: Business, published: list[ContentItem]) -> list[str]:
    """What the client did not supply, and the concrete cost of it.

    Kept factual rather than reproachful: the point is to make the next month
    better, and an owner who feels blamed sends less, not more.
    """
    from app.services.brand_assets import media_readiness

    gaps: list[str] = []
    media = media_readiness(business.id)

    if not media["footage"]:
        gaps.append(
            "Video kadr yuborilmadi — shu sababli reels o'rniga matnli karta chiqdi. "
            "Oylik brifdagi 3-4 ta kadr yetarli."
        )
    if not media["photos"]:
        gaps.append(
            "Markazning haqiqiy surati yo'q — postlar generatsiya qilingan rasm bilan "
            "chiqdi. Bitta suratga olish kuni buni butunlay o'zgartiradi."
        )
    if not business.capabilities.instagram:
        gaps.append("Instagram tarifga kirmagan — kontent faqat Telegramga chiqdi.")
    return gaps


def render_telegram(report: ClientReport) -> str:
    """The report as one message, ordered by what the client cares about."""
    lines = [
        f"📊 <b>{report.label.capitalize()} — hisobot</b>",
        report.business,
        "",
        "<b>Natija</b>",
        f"• Botga yozganlar: <b>{report.leads_total}</b>",
    ]
    if report.leads_total:
        lines.append(
            f"  — bog'lanilgan: {report.leads_contacted} · javobsiz: {report.leads_new}"
        )
        if report.leads_new:
            lines.append(f"  ⚠️ {report.leads_new} ta odam hali javob kutyapti.")
    else:
        lines.append("  Bu oy botga hech kim yozmadi.")

    lines += ["", "<b>Chiqarilgan kontent</b>", f"• Jami: {report.published_total} ta"]
    for label, count in sorted(report.by_type.items(), key=lambda kv: -kv[1]):
        lines.append(f"  — {label}: {count}")
    if report.avg_quality:
        lines.append(f"• O'rtacha muharrir bahosi: {report.avg_quality}/10")

    if report.top_posts:
        lines += ["", "<b>Eng yaxshi postlar</b>"]
        for index, post in enumerate(report.top_posts, 1):
            tail = f" · {post.reactions} reaksiya" if post.reactions is not None else ""
            lines.append(
                f"{index}. {post.headline} ({post.content_type}, "
                f"{post.published_on.strftime('%d.%m')}){tail}"
            )

    if report.scheduled_next:
        lines += ["", f"<b>Keyingi oy</b>\n• {report.scheduled_next} ta kontent tayyor turibdi"]

    if report.gaps:
        lines += ["", "<b>Nima yetishmadi</b>"]
        lines += [f"• {gap}" for gap in report.gaps]

    if report.unmeasured:
        lines += ["", "<b>O'lchanmagani</b>"]
        lines += [f"• {note}" for note in report.unmeasured]

    return "\n".join(lines)
