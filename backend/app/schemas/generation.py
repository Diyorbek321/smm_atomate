"""Request/response models for manual generation triggers and analytics."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ContentPillar, ContentType, Platform


class GeneratePlanRequest(BaseModel):
    business_id: uuid.UUID
    starts_on: date | None = None
    horizon_days: int = Field(default=7, ge=1, le=31)
    posts_count: int | None = Field(default=None, ge=3, le=60)
    extra_instructions: str = ""
    send_for_review: bool = True


class GenerateItemRequest(BaseModel):
    business_id: uuid.UUID
    content_type: ContentType = ContentType.FEED_POST
    pillar: ContentPillar = ContentPillar.SALES
    topic: str = ""
    platform: Platform = Platform.BOTH
    scheduled_at: datetime | None = None
    extra_instructions: str = ""
    render_image: bool = True
    send_for_review: bool = True


class RegenerateRequest(BaseModel):
    instruction: str = ""
    regenerate_image: bool = False


class GenerationTaskResponse(BaseModel):
    task_id: str | None = None
    status: str = "queued"
    message: str = ""
    plan_id: uuid.UUID | None = None
    item_ids: list[uuid.UUID] = Field(default_factory=list)


class PublishNowRequest(BaseModel):
    force: bool = False


class AnalyticsSummary(BaseModel):
    active_businesses: int = 0
    total_businesses: int = 0
    scheduled_today: int = 0
    pending_review: int = 0
    published_24h: int = 0
    failed_24h: int = 0
    published_total: int = 0
    approval_rate: float = 0.0
    avg_quality_score: float = 0.0
    pillar_distribution: dict[str, int] = Field(default_factory=dict)
    content_type_distribution: dict[str, int] = Field(default_factory=dict)
    upcoming: list[dict[str, Any]] = Field(default_factory=list)
    est_api_cost_usd: float = 0.0


class BusinessAnalytics(BaseModel):
    business_id: uuid.UUID
    business_name: str
    items_total: int = 0
    published: int = 0
    pending_review: int = 0
    failed: int = 0
    approval_rate: float = 0.0
    avg_quality_score: float = 0.0
    knowledge_completeness: float = 0.0
    by_pillar: dict[str, int] = Field(default_factory=dict)
    last_published_at: datetime | None = None
