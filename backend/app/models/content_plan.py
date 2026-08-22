"""Weekly / monthly content plan (the strategy container)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import ContentPlanStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.business import Business
    from app.models.content_item import ContentItem


class ContentPlan(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "content_plans"
    __table_args__ = (
        UniqueConstraint("business_id", "year", "week_number", name="uq_plan_business_year_week"),
        Index("ix_content_plans_business_status", "business_id", "status"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)     # ISO week 1..53
    month_number: Mapped[int] = mapped_column(Integer, nullable=False)    # 1..12
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[ContentPlanStatus] = mapped_column(
        SAEnum(
            ContentPlanStatus,
            name="content_plan_status",
            native_enum=False,
            length=32,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ContentPlanStatus.DRAFT,
        nullable=False,
        index=True,
    )

    # Strategist output: theme, goals, pillar counts, slot matrix.
    strategy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    generation_error: Mapped[str | None] = mapped_column(Text)

    business: Mapped[Business] = relationship(back_populates="content_plans")
    items: Mapped[list[ContentItem]] = relationship(
        back_populates="content_plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ContentItem.scheduled_at",
    )

    @property
    def pillar_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            key = str(item.pillar)
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def label(self) -> str:
        return self.title or f"{self.year}-W{self.week_number:02d}"
