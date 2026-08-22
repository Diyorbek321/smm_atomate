"""Prompt Studio schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ContentPillar
from app.schemas.common import ORMModel


class PromptTemplateCreate(BaseModel):
    business_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=160)
    agent: str = Field(default="copywriter", max_length=40)
    pillar: ContentPillar | None = None
    system_prompt: str = Field(min_length=10)
    image_style: str = "cinematic"
    aspect_ratio: str = "4:5"
    negative_prompt: str | None = None
    is_active: bool = True


class PromptTemplateUpdate(BaseModel):
    name: str | None = None
    agent: str | None = None
    pillar: ContentPillar | None = None
    system_prompt: str | None = None
    image_style: str | None = None
    aspect_ratio: str | None = None
    negative_prompt: str | None = None
    is_active: bool | None = None


class PromptTemplateRead(ORMModel):
    id: uuid.UUID
    business_id: uuid.UUID | None
    name: str
    agent: str
    pillar: ContentPillar | None
    system_prompt: str
    image_style: str
    aspect_ratio: str
    negative_prompt: str | None
    is_active: bool
    version: int
    versions: list[dict[str, Any]]
    usage_count: int
    engagement_lift: float
    created_at: datetime
    updated_at: datetime
