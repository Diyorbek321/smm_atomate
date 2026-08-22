"""Timezone-aware scheduling helpers (business local time ⇄ UTC)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def get_tz(name: str | None = None) -> ZoneInfo:
    try:
        return ZoneInfo(name or settings.default_timezone)
    except Exception:
        return ZoneInfo("UTC")


def to_utc(value: datetime, tz_name: str | None = None) -> datetime:
    """Interpret naive datetimes as business-local, return an aware UTC value."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=get_tz(tz_name))
    return value.astimezone(UTC)


def to_local(value: datetime, tz_name: str | None = None) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(get_tz(tz_name))


def week_bounds(anchor: date) -> tuple[date, date]:
    """Monday..Sunday of the ISO week containing `anchor`."""
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def next_monday(anchor: date | None = None) -> date:
    anchor = anchor or utcnow().date()
    return anchor + timedelta(days=(7 - anchor.weekday()) % 7 or 7)


def slot_to_datetime(start: date, day_offset: int, hour: int, tz_name: str | None = None) -> datetime:
    """Build the UTC publish timestamp for a strategist slot."""
    local_day = start + timedelta(days=max(0, day_offset))
    hour = min(23, max(0, hour))
    local_dt = datetime.combine(local_day, time(hour=hour, minute=0)).replace(tzinfo=get_tz(tz_name))
    return local_dt.astimezone(UTC)


def spread_slots(
    start: date,
    count: int,
    hours: list[int],
    horizon_days: int = 7,
    tz_name: str | None = None,
) -> list[datetime]:
    """Evenly distribute `count` posts across `horizon_days` at `hours`.

    Deterministic — the same inputs always yield the same schedule.
    """
    if count <= 0:
        return []
    hours = sorted({min(23, max(0, int(h))) for h in (hours or [10])}) or [10]
    slots: list[datetime] = []
    per_day = max(1, -(-count // max(1, horizon_days)))
    day = 0
    while len(slots) < count and day < horizon_days * 2:
        for hour in hours[:per_day]:
            if len(slots) >= count:
                break
            offset = day % horizon_days + (day // horizon_days) * horizon_days
            slots.append(slot_to_datetime(start, offset, hour, tz_name))
        day += 1
    return sorted(slots[:count])


def humanize(value: datetime, tz_name: str | None = None) -> str:
    """`2026-08-20 18:00` in the business timezone — used in bot messages."""
    return to_local(value, tz_name).strftime("%d.%m.%Y %H:%M")


def iso_week(value: date) -> tuple[int, int]:
    iso = value.isocalendar()
    return iso.year, iso.week
