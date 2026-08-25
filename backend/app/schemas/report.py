"""Wire format for the monthly client report."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class TopPostRead(BaseModel):
    headline: str
    content_type: str
    reactions: int | None = None
    published_on: date


class ClientReportRead(BaseModel):
    business: str
    period_start: date
    period_end: date
    label: str = ""

    published_total: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    top_posts: list[TopPostRead] = Field(default_factory=list)

    leads_total: int = 0
    leads_new: int = 0
    leads_contacted: int = 0

    avg_quality: float = 0.0
    scheduled_next: int = 0

    unmeasured: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    #: Ready-to-send Telegram HTML, so bot and dashboard never diverge.
    telegram_text: str = ""
