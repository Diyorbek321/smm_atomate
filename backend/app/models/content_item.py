"""A single publishable unit produced by the agent pipeline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import (
    ContentItemStatus,
    ContentPillar,
    ContentType,
    Platform,
    PublishState,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.business import Business
    from app.models.content_plan import ContentPlan


def _enum(enum_cls: type, name: str, length: int = 32) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
    )


#: Written into ``review_notes`` when a plan is regenerated and the previous
#: draft is retired to make room. It is a rejection in the database and not one
#: in the owner's head, so anything that reads rejections as owner feedback —
#: the planner's "do not write this again" list — has to tell the two apart.
SUPERSEDED_NOTE = "qayta yaratilgani uchun almashtirildi"


class ContentItem(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "content_items"
    __table_args__ = (
        Index("ix_items_due", "status", "scheduled_at"),
        Index("ix_items_business_status", "business_id", "status"),
        Index("ix_items_plan", "content_plan_id"),
    )

    content_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_plans.id", ondelete="CASCADE")
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )

    # --- Editorial metadata ---------------------------------------------
    content_type: Mapped[ContentType] = mapped_column(_enum(ContentType, "content_type"), nullable=False)
    pillar: Mapped[ContentPillar] = mapped_column(
        _enum(ContentPillar, "content_pillar"), default=ContentPillar.EDUCATIONAL, nullable=False
    )
    platform: Mapped[Platform] = mapped_column(
        _enum(Platform, "platform"), default=Platform.BOTH, nullable=False
    )
    topic: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    headline: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    hook: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    cta: Mapped[str] = mapped_column(String(300), default="", nullable=False)

    # --- Copy -------------------------------------------------------------
    caption_tg: Mapped[str] = mapped_column(Text, default="", nullable=False)
    caption_ig: Mapped[str] = mapped_column(Text, default="", nullable=False)
    hashtags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # --- Visuals ----------------------------------------------------------
    image_url: Mapped[str | None] = mapped_column(String(1024))
    #: Motion clip rendered for stories/announcements; image_url stays the poster.
    video_url: Mapped[str | None] = mapped_column(String(1024))
    image_prompt: Mapped[str | None] = mapped_column(Text)
    #: [{"index":1,"title":"...","body":"...","image_url":"..."}]
    carousel_slides: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    #: quiz/poll payload: {"question": "...", "answers": [...], "correct_option_id": 1}
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    #: reels script: {"scenes":[...], "voiceover":"...", "duration_sec": 30}
    script: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # --- Scheduling / lifecycle ------------------------------------------
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ContentItemStatus] = mapped_column(
        _enum(ContentItemStatus, "content_item_status"),
        default=ContentItemStatus.DRAFT,
        nullable=False,
        index=True,
    )

    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    regeneration_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)

    # --- Review trail -----------------------------------------------------
    # Telegram chat/message ids exceed int32 (user ids are already > 2^31).
    review_message_id: Mapped[int | None] = mapped_column(BigInteger)
    review_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_by: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sent_for_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Publication results ---------------------------------------------
    tg_state: Mapped[PublishState] = mapped_column(
        _enum(PublishState, "publish_state"), default=PublishState.PENDING, nullable=False
    )
    ig_state: Mapped[PublishState] = mapped_column(
        _enum(PublishState, "publish_state_ig"), default=PublishState.PENDING, nullable=False
    )
    tg_message_id: Mapped[str | None] = mapped_column(String(64))
    ig_media_id: Mapped[str | None] = mapped_column(String(64))

    # --- QA ---------------------------------------------------------------
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    editor_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    ai_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    #: What the post did once it was live — reactions so far, when they were
    #: last counted. Empty until the first reaction lands; a post with no
    #: reactions and a post never measured are different things, and the
    #: strategist has to be able to tell them apart.
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    content_plan: Mapped[ContentPlan | None] = relationship(back_populates="items")
    business: Mapped[Business] = relationship(back_populates="content_items")

    # ------------------------------------------------------------------ #
    @property
    def is_due(self) -> bool:
        return (
            self.status == ContentItemStatus.APPROVED
            and self.scheduled_at is not None
            and self.scheduled_at <= datetime.now(UTC)
        )

    @property
    def needs_telegram(self) -> bool:
        return self.platform in (Platform.TELEGRAM, Platform.BOTH)

    @property
    def needs_instagram(self) -> bool:
        if self.content_type in (ContentType.TELEGRAM_QUIZ, ContentType.REELS_SCRIPT, ContentType.VIDEO_POST):
            return False
        return self.platform in (Platform.INSTAGRAM, Platform.BOTH)

    @property
    def slide_image_urls(self) -> list[str]:
        return [s["image_url"] for s in (self.carousel_slides or []) if s.get("image_url")]

    def short_title(self, limit: int = 60) -> str:
        base = self.headline or self.topic or str(self.content_type)
        return base if len(base) <= limit else base[: limit - 1] + "…"

    def mark_failed(self, error: str) -> None:
        self.status = ContentItemStatus.FAILED
        self.last_error = error[:2000]
        self.retry_count += 1
