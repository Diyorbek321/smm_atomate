"""Everything the AI needs to know about a business."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.business import Business


class KnowledgeBase(UUIDMixin, TimestampMixin, Base):
    """Structured brand memory, filled by the OnboardingAgent and the API.

    JSON columns keep the shape flexible per vertical while still being
    queryable in Postgres (JSONB).
    """

    __tablename__ = "knowledge_bases"

    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # [{"name": "IELTS intensiv", "description": "...", "duration": "3 oy"}]
    key_offerings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    # [{"item": "IELTS intensiv", "price": 600000, "currency": "UZS", "note": "oyiga"}]
    prices: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    # ["Yagona 8.0 IELTS o'qituvchisi", "Kafolatli natija"]
    usps: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    # [{"name": "Aziz aka", "role": "IELTS teacher", "achievements": "8.0 overall"}]
    teacher_profiles: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    # [{"q": "Darslar qachon?", "a": "Har kuni 18:00 da"}]
    faq: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    # [{"name": "Dilnoza", "result": "IELTS 7.5", "quote": "..."}]
    success_stories: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    # Free-form dictation from the owner (voice notes land here too).
    raw_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Contact / conversion surface
    phone: Mapped[str | None] = mapped_column(String(64))
    telegram_username: Mapped[str | None] = mapped_column(String(80))
    instagram_username: Mapped[str | None] = mapped_column(String(80))
    website: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255))
    working_hours: Mapped[str | None] = mapped_column(String(160))

    # Visual identity used by the HTML card renderer.
    brand_colors: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(512))

    # Guardrails for the copywriter.
    banned_topics: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    preferred_hashtags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    competitors: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    completeness_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    business: Mapped[Business] = relationship(back_populates="knowledge_base")

    # ------------------------------------------------------------------ #
    REQUIRED_FIELDS = ("key_offerings", "prices", "usps", "phone", "target_audience")

    def compute_completeness(self) -> float:
        """0.0 – 1.0 score used to decide whether onboarding may finish."""
        checks = [
            bool(self.key_offerings),
            bool(self.prices),
            bool(self.usps),
            bool(self.teacher_profiles or self.success_stories),
            bool(self.faq),
            bool(self.phone or self.telegram_username),
            bool(self.raw_notes and len(self.raw_notes) > 40),
        ]
        score = round(sum(checks) / len(checks), 3)
        self.completeness_score = score
        return score

    @property
    def missing_fields(self) -> list[str]:
        missing = []
        if not self.key_offerings:
            missing.append("key_offerings")
        if not self.prices:
            missing.append("prices")
        if not self.usps:
            missing.append("usps")
        if not (self.phone or self.telegram_username):
            missing.append("contact")
        if not self.faq:
            missing.append("faq")
        if not (self.teacher_profiles or self.success_stories):
            missing.append("social_proof")
        return missing

    @property
    def contact_line(self) -> str:
        """Single CTA line appended to every caption."""
        parts: list[str] = []
        if self.phone:
            parts.append(f"📞 {self.phone}")
        if self.telegram_username:
            handle = self.telegram_username.lstrip("@")
            parts.append(f"✍️ @{handle}")
        if self.address:
            parts.append(f"📍 {self.address}")
        return "\n".join(parts)

    def to_prompt_context(self) -> str:
        """Compact, token-efficient rendering for LLM prompts."""
        import json

        def _short(value: Any, limit: int = 12) -> Any:
            return value[:limit] if isinstance(value, list) else value

        payload = {
            "key_offerings": _short(self.key_offerings),
            "prices": _short(self.prices),
            "usps": _short(self.usps, 8),
            "teachers": _short(self.teacher_profiles, 6),
            "faq": _short(self.faq, 8),
            "success_stories": _short(self.success_stories, 6),
            "contacts": {
                "phone": self.phone,
                "telegram": self.telegram_username,
                "instagram": self.instagram_username,
                "address": self.address,
                "working_hours": self.working_hours,
            },
            "banned_topics": self.banned_topics,
            "preferred_hashtags": _short(self.preferred_hashtags, 15),
            "notes": (self.raw_notes or "")[:1500],
        }
        return json.dumps(payload, ensure_ascii=False, indent=None)
