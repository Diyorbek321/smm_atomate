"""Business, its admins and API credentials."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import EncryptedString
from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import AdminRole, BusinessCategory, Language, Plan, ToneOfVoice

if TYPE_CHECKING:  # pragma: no cover
    from app.core.plans import PlanCapabilities
    from app.models.content_item import ContentItem
    from app.models.content_plan import ContentPlan
    from app.models.knowledge_base import KnowledgeBase


def _enum(enum_cls: type, name: str) -> SAEnum:
    """VARCHAR-backed enum storing `.value` (portable + migration friendly)."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class Business(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    plan: Mapped[Plan] = mapped_column(
        _enum(Plan, "plan"), default=Plan.START, server_default=Plan.START.value, nullable=False, index=True
    )
    category: Mapped[BusinessCategory] = mapped_column(
        _enum(BusinessCategory, "business_category"), default=BusinessCategory.EDUCATION, nullable=False
    )
    tone_of_voice: Mapped[ToneOfVoice] = mapped_column(
        _enum(ToneOfVoice, "tone_of_voice"), default=ToneOfVoice.CASUAL, nullable=False
    )
    target_audience: Mapped[str] = mapped_column(Text, default="", nullable=False)
    language: Mapped[Language] = mapped_column(
        _enum(Language, "language"), default=Language.UZ, nullable=False
    )
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Operational preferences (posting hours, weekly volume, auto-approve...)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    credentials: Mapped[BusinessCredentials | None] = relationship(
        back_populates="business", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    knowledge_base: Mapped[KnowledgeBase | None] = relationship(
        back_populates="business", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    admins: Mapped[list[BusinessAdmin]] = relationship(
        back_populates="business", cascade="all, delete-orphan", lazy="selectin"
    )
    content_plans: Mapped[list[ContentPlan]] = relationship(
        back_populates="business", cascade="all, delete-orphan", lazy="noload"
    )
    content_items: Mapped[list[ContentItem]] = relationship(
        back_populates="business", cascade="all, delete-orphan", lazy="noload"
    )

    # -- convenience ------------------------------------------------------
    @property
    def posting_hours(self) -> list[int]:
        hours = self.settings.get("posting_hours") if self.settings else None
        if isinstance(hours, list) and hours:
            return [int(h) for h in hours]
        return [9, 13, 18]

    @property
    def capabilities(self) -> "PlanCapabilities":
        """What this client's tier unlocks, including any per-business grants."""
        from app.core.plans import capabilities_for

        return capabilities_for(self.plan, (self.settings or {}).get("plan_overrides"))

    @property
    def posts_per_week(self) -> int:
        """Requested volume, capped by the tier the client pays for."""
        value = (self.settings or {}).get("posts_per_week", 10)
        return max(4, min(int(value), self.capabilities.max_posts_per_week))

    @property
    def auto_approve(self) -> bool:
        return bool((self.settings or {}).get("auto_approve", False))


class BusinessCredentials(UUIDMixin, TimestampMixin, Base):
    """Per-business channel tokens. All secrets are encrypted at rest."""

    __tablename__ = "business_credentials"

    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Telegram
    tg_bot_token: Mapped[str | None] = mapped_column(EncryptedString(512))
    tg_channel_id: Mapped[str | None] = mapped_column(String(128))
    tg_discussion_chat_id: Mapped[str | None] = mapped_column(String(128))

    # Instagram / Meta
    ig_access_token: Mapped[str | None] = mapped_column(EncryptedString(1024))
    ig_account_id: Mapped[str | None] = mapped_column(String(64))
    ig_page_id: Mapped[str | None] = mapped_column(String(64))
    ig_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    instagram_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    business: Mapped[Business] = relationship(back_populates="credentials")

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_enabled and self.tg_bot_token and self.tg_channel_id)

    @property
    def instagram_ready(self) -> bool:
        return bool(self.instagram_enabled and self.ig_access_token and self.ig_account_id)


class BusinessAdmin(UUIDMixin, TimestampMixin, Base):
    """Telegram user allowed to review/approve content for a business."""

    __tablename__ = "business_admins"
    __table_args__ = (
        UniqueConstraint("business_id", "telegram_user_id", name="uq_admin_business_tg_user"),
        Index("ix_business_admins_tg_user", "telegram_user_id"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(160))
    username: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[AdminRole] = mapped_column(_enum(AdminRole, "admin_role"), default=AdminRole.OWNER, nullable=False)
    receives_reviews: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    business: Mapped[Business] = relationship(back_populates="admins")

    @property
    def can_approve(self) -> bool:
        return self.role in (AdminRole.OWNER, AdminRole.MANAGER)
