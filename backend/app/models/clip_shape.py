"""The shape of every clip a business has shipped — its structural memory.

:class:`app.models.content_item.ContentItem` remembers posts, and the planner
reads it back so a topic is not proposed twice. Clips rendered by
:func:`app.tasks.generation.render_brief_clip` never created one: they render
and go straight to Telegram, so the video path had no history of any kind and
:mod:`app.services.promo_variety` would have had nothing to read.

One row per rendered clip, and only the structure — no copy, no video path.
What was *said* is the caption's problem; this table exists to answer one
question, "what shape have we already used", as cheaply as possible.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ClipShape(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "clip_shapes"
    __table_args__ = (Index("ix_clip_shapes_business_created", "business_id", "created_at"),)

    #: CASCADE, unlike leads: a phone number outlives the business it came
    #: from, a record of how its videos were built does not.
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(300), default="")
    skeleton: Mapped[str] = mapped_column(String(32), default="")
    opening: Mapped[str] = mapped_column(String(48), default="")
    #: Archetype names in the order they were composed. A list rather than a
    #: joined string because order carries the meaning and a delimiter would
    #: have to be defended against archetype names forever.
    archetypes: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    scenes: Mapped[int] = mapped_column(Integer, default=0)
    mood: Mapped[str] = mapped_column(String(24), default="")
    #: Filename only, not a path: the storage root moves between environments
    #: and this is compared against a freshly listed library, never opened.
    backdrop: Mapped[str] = mapped_column(String(160), default="")
    seconds: Mapped[int] = mapped_column(Integer, default=0)
