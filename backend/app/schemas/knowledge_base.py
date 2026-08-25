"""Knowledge base schemas (also used as the Gemini extraction contract)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class Offering(BaseModel):
    name: str
    description: str = ""
    duration: str | None = None
    level: str | None = None


class PriceItem(BaseModel):
    item: str
    price: float | None = None
    currency: str = "UZS"
    note: str | None = None


class TeacherProfile(BaseModel):
    name: str
    role: str = ""
    achievements: str = ""
    experience_years: int | None = None


class FaqItem(BaseModel):
    q: str
    a: str


class SuccessStory(BaseModel):
    name: str
    result: str = ""
    quote: str = ""


class KnowledgeBaseUpdate(BaseModel):
    key_offerings: list[dict[str, Any]] | None = None
    prices: list[dict[str, Any]] | None = None
    usps: list[str] | None = None
    teacher_profiles: list[dict[str, Any]] | None = None
    faq: list[dict[str, Any]] | None = None
    success_stories: list[dict[str, Any]] | None = None
    raw_notes: str | None = None
    phone: str | None = None
    telegram_username: str | None = None
    instagram_username: str | None = None
    website: str | None = None
    address: str | None = None
    working_hours: str | None = None
    brand_colors: dict[str, Any] | None = None
    logo_url: str | None = None
    #: palette / lighting / lens / grade / subject — see services/style_dna.py
    visual_style: dict[str, Any] | None = None
    brand_kit: dict[str, Any] | None = None
    banned_topics: list[str] | None = None
    preferred_hashtags: list[str] | None = None
    competitors: list[str] | None = None


class KnowledgeBaseRead(ORMModel):
    id: uuid.UUID
    business_id: uuid.UUID
    key_offerings: list[dict[str, Any]]
    prices: list[dict[str, Any]]
    usps: list[str]
    teacher_profiles: list[dict[str, Any]]
    faq: list[dict[str, Any]]
    success_stories: list[dict[str, Any]]
    raw_notes: str
    phone: str | None
    telegram_username: str | None
    instagram_username: str | None
    website: str | None
    address: str | None
    working_hours: str | None
    brand_colors: dict[str, Any]
    logo_url: str | None
    visual_style: dict[str, Any]
    brand_kit: dict[str, Any]
    banned_topics: list[str]
    preferred_hashtags: list[str]
    competitors: list[str]
    completeness_score: float
    version: int


class KnowledgeExtraction(BaseModel):
    """Shape the OnboardingAgent asks Gemini to return."""

    key_offerings: list[Offering] = Field(default_factory=list)
    prices: list[PriceItem] = Field(default_factory=list)
    usps: list[str] = Field(default_factory=list)
    teacher_profiles: list[TeacherProfile] = Field(default_factory=list)
    faq: list[FaqItem] = Field(default_factory=list)
    success_stories: list[SuccessStory] = Field(default_factory=list)
    phone: str | None = None
    telegram_username: str | None = None
    instagram_username: str | None = None
    address: str | None = None
    working_hours: str | None = None
    target_audience: str | None = None
    preferred_hashtags: list[str] = Field(default_factory=list)
    next_question: str | None = Field(
        default=None, description="Follow-up question in Uzbek, or null when the profile is complete"
    )
    summary: str = ""
