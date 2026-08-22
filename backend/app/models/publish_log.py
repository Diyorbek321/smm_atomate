"""Append-only audit trail of every publication attempt."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import Platform, PublishState


class PublishLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "publish_logs"
    __table_args__ = (Index("ix_publish_logs_item", "content_item_id", "created_at"),)

    content_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[Platform] = mapped_column(
        SAEnum(
            Platform,
            name="log_platform",
            native_enum=False,
            length=32,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    state: Mapped[PublishState] = mapped_column(
        SAEnum(
            PublishState,
            name="log_state",
            native_enum=False,
            length=32,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
