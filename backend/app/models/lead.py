"""Leads captured by the bot — strangers who wrote in from a post CTA."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Lead(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (Index("ix_leads_business_created", "business_id", "created_at"),)

    #: SET NULL so deleting a business keeps the contact — a phone number is money.
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True
    )
    #: Nullable since Instagram: a lead now arrives from one channel or the
    #: other and carries the id of whichever it came through.
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    #: Instagram-scoped sender id. A string, not a number: Meta documents it as
    #: an opaque id and only guarantees it is stable per app, per account.
    ig_user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    username: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    interest: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="bot")
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | contacted
    #: Set once the client's CRM accepted the lead; the retry sweep sends
    #: whatever has a phone and is still None here.
    crm_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    crm_error: Mapped[str | None] = mapped_column(String(255))
