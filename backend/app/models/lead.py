"""Leads captured by the bot — strangers who wrote in from a post CTA."""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
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
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    username: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    interest: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="bot")
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | contacted
