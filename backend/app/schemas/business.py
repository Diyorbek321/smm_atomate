"""Business / credentials / admin schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.security import mask_secret
from app.models.enums import AdminRole, BusinessCategory, Language, Plan, ToneOfVoice
from app.schemas.common import ORMModel


class BusinessBase(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    plan: Plan = Plan.START
    category: BusinessCategory = BusinessCategory.EDUCATION
    tone_of_voice: ToneOfVoice = ToneOfVoice.CASUAL
    target_audience: str = Field(default="", max_length=2000)
    language: Language = Language.UZ
    timezone: str = "Asia/Tashkent"
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, value: str) -> str:
        import zoneinfo

        try:
            zoneinfo.ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"Unknown timezone: {value}") from exc
        return value


class BusinessCreate(BusinessBase):
    slug: str | None = Field(default=None, max_length=80)


class BusinessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    plan: Plan | None = None
    category: BusinessCategory | None = None
    tone_of_voice: ToneOfVoice | None = None
    target_audience: str | None = None
    language: Language | None = None
    timezone: str | None = None
    is_active: bool | None = None
    settings: dict[str, Any] | None = None


class PlanCapabilitiesRead(ORMModel):
    """Flattened capability matrix so the dashboard can grey out what is locked.

    Reads straight off ``Business.capabilities`` — the dataclass in
    app/core/plans.py — so the API can never drift from what the code enforces.
    """

    max_posts_per_week: int
    content_types: list[str]
    instagram: bool
    video: bool
    video_editing: bool
    ai_video: bool
    lead_autoreply: bool

    @field_validator("content_types", mode="before")
    @classmethod
    def _sorted_values(cls, value: Any) -> list[str]:
        return sorted(str(getattr(item, "value", item)) for item in value)


class BusinessRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str | None
    plan: Plan
    capabilities: PlanCapabilitiesRead
    category: BusinessCategory
    tone_of_voice: ToneOfVoice
    target_audience: str
    language: Language
    timezone: str
    is_active: bool
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CredentialsUpdate(BaseModel):
    tg_bot_token: str | None = None
    tg_channel_id: str | None = None
    tg_discussion_chat_id: str | None = None
    ig_access_token: str | None = None
    ig_account_id: str | None = None
    ig_page_id: str | None = None
    telegram_enabled: bool | None = None
    instagram_enabled: bool | None = None


class CredentialsRead(ORMModel):
    business_id: uuid.UUID
    tg_bot_token: str | None = None
    tg_channel_id: str | None = None
    ig_access_token: str | None = None
    ig_account_id: str | None = None
    ig_page_id: str | None = None
    telegram_enabled: bool
    instagram_enabled: bool
    telegram_ready: bool = False
    instagram_ready: bool = False

    @field_validator("tg_bot_token", "ig_access_token", mode="after")
    @classmethod
    def _mask(cls, value: str | None) -> str | None:
        return mask_secret(value)


class AdminCreate(BaseModel):
    telegram_user_id: int
    full_name: str | None = None
    username: str | None = None
    role: AdminRole = AdminRole.OWNER
    receives_reviews: bool = True


class AdminRead(ORMModel):
    id: uuid.UUID
    business_id: uuid.UUID
    telegram_user_id: int
    full_name: str | None
    username: str | None
    role: AdminRole
    receives_reviews: bool
