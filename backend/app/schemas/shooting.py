"""Wire format for the monthly shooting brief."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ShotRead(BaseModel):
    key: str
    title: str
    what: str
    how: str
    kind: str = "video"
    seconds: int = 0
    why: str = ""


class ShootingBriefRead(BaseModel):
    business: str
    month: date
    shots: list[ShotRead] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    video_count: int = 0
    photo_count: int = 0
    total_seconds: int = 0
    #: Ready-to-send Telegram HTML, so the dashboard and the bot never drift.
    telegram_text: str = ""
