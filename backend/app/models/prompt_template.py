"""Editable system prompts used by the agents (Prompt Studio backend)."""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import ContentPillar


class PromptTemplate(UUIDMixin, TimestampMixin, Base):
    """A named, versioned prompt override.

    When a template exists for (business_id, agent, pillar) the agent uses it
    instead of the built-in default, so prompts can be tuned without a deploy.
    """

    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_prompt_business_name"),)

    business_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    agent: Mapped[str] = mapped_column(String(40), default="copywriter", nullable=False, index=True)
    pillar: Mapped[ContentPillar | None] = mapped_column(
        SAEnum(
            ContentPillar,
            name="prompt_pillar",
            native_enum=False,
            length=32,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    image_style: Mapped[str] = mapped_column(String(64), default="cinematic", nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="4:5", nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: [{"version":1,"system_prompt":"...","saved_at":"..."}]
    versions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement_lift: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    def push_version(self) -> None:
        """Snapshot the current prompt before overwriting it."""
        from datetime import datetime

        history = list(self.versions or [])
        history.append(
            {
                "version": self.version,
                "system_prompt": self.system_prompt,
                "saved_at": datetime.now(UTC).isoformat(),
            }
        )
        self.versions = history[-20:]
        self.version += 1
