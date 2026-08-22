"""Content plan / item schemas + the JSON contracts used by the agents."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    ContentItemStatus,
    ContentPillar,
    ContentPlanStatus,
    ContentType,
    Platform,
    PublishState,
)
from app.schemas.common import ORMModel

# --------------------------------------------------------------------------- #
# Content plan
# --------------------------------------------------------------------------- #


class ContentPlanCreate(BaseModel):
    business_id: uuid.UUID
    starts_on: date | None = None
    horizon_days: int = Field(default=7, ge=1, le=31)
    posts_count: int | None = Field(default=None, ge=3, le=60)
    title: str | None = None
    notes: str = ""


class ContentPlanUpdate(BaseModel):
    title: str | None = None
    status: ContentPlanStatus | None = None
    notes: str | None = None
    strategy: dict[str, Any] | None = None


class ContentPlanRead(ORMModel):
    id: uuid.UUID
    business_id: uuid.UUID
    title: str
    year: int
    week_number: int
    month_number: int
    starts_on: date
    ends_on: date
    status: ContentPlanStatus
    strategy: dict[str, Any]
    notes: str
    generation_error: str | None
    created_at: datetime


class ContentPlanDetail(ContentPlanRead):
    items: list[ContentItemRead] = Field(default_factory=list)
    pillar_counts: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Content item
# --------------------------------------------------------------------------- #


class ContentItemCreate(BaseModel):
    business_id: uuid.UUID
    content_plan_id: uuid.UUID | None = None
    content_type: ContentType
    pillar: ContentPillar = ContentPillar.EDUCATIONAL
    platform: Platform = Platform.BOTH
    topic: str = ""
    headline: str = ""
    caption_tg: str = ""
    caption_ig: str = ""
    hashtags: list[str] = Field(default_factory=list)
    image_url: str | None = None
    image_prompt: str | None = None
    carousel_slides: list[dict[str, Any]] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime
    status: ContentItemStatus = ContentItemStatus.PENDING_REVIEW


class ContentItemUpdate(BaseModel):
    topic: str | None = None
    headline: str | None = None
    hook: str | None = None
    cta: str | None = None
    caption_tg: str | None = None
    caption_ig: str | None = None
    hashtags: list[str] | None = None
    image_url: str | None = None
    image_prompt: str | None = None
    carousel_slides: list[dict[str, Any]] | None = None
    options: dict[str, Any] | None = None
    script: dict[str, Any] | None = None
    scheduled_at: datetime | None = None
    platform: Platform | None = None
    status: ContentItemStatus | None = None
    review_notes: str | None = None


class ContentItemRead(ORMModel):
    id: uuid.UUID
    business_id: uuid.UUID
    content_plan_id: uuid.UUID | None
    content_type: ContentType
    pillar: ContentPillar
    platform: Platform
    topic: str
    headline: str
    hook: str
    cta: str
    caption_tg: str
    caption_ig: str
    hashtags: list[str]
    image_url: str | None
    image_prompt: str | None
    video_url: str | None
    carousel_slides: list[dict[str, Any]]
    options: dict[str, Any]
    script: dict[str, Any]
    scheduled_at: datetime
    published_at: datetime | None
    status: ContentItemStatus
    retry_count: int
    regeneration_count: int
    last_error: str | None
    quality_score: float
    editor_report: dict[str, Any]
    tg_state: PublishState
    ig_state: PublishState
    tg_message_id: str | None
    ig_media_id: str | None
    created_at: datetime


class ContentItemFilter(BaseModel):
    business_id: uuid.UUID | None = None
    content_plan_id: uuid.UUID | None = None
    status: ContentItemStatus | None = None
    content_type: ContentType | None = None
    pillar: ContentPillar | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class BulkStatusUpdate(BaseModel):
    item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    status: ContentItemStatus

    @field_validator("status")
    @classmethod
    def _allowed(cls, value: ContentItemStatus) -> ContentItemStatus:
        allowed = {ContentItemStatus.APPROVED, ContentItemStatus.REJECTED, ContentItemStatus.PENDING_REVIEW}
        if value not in allowed:
            raise ValueError(f"status must be one of {[s.value for s in allowed]}")
        return value


# --------------------------------------------------------------------------- #
# Agent I/O contracts
# --------------------------------------------------------------------------- #


class PlanSlot(BaseModel):
    """One row of the strategist's content matrix."""

    day_offset: int = Field(ge=0, le=31)
    hour: int = Field(default=10, ge=0, le=23)
    pillar: ContentPillar
    content_type: ContentType
    topic: str
    angle: str = ""
    goal: str = ""
    platform: Platform = Platform.BOTH


class StrategyOutput(BaseModel):
    theme: str = ""
    objectives: list[str] = Field(default_factory=list)
    slots: list[PlanSlot] = Field(default_factory=list)
    notes: str = ""


class CopyOutput(BaseModel):
    headline: str = ""
    hook: str = ""
    caption_tg: str = ""
    caption_ig: str = ""
    cta: str = ""
    hashtags: list[str] = Field(default_factory=list)
    #: carousel: [{"index":1,"title":"..","body":".."}]
    slides: list[dict[str, Any]] = Field(default_factory=list)
    #: quiz: {"question":"..","answers":[..],"correct_option_id":0,"explanation":".."}
    quiz: dict[str, Any] = Field(default_factory=dict)
    #: reels: {"duration_sec":30,"scenes":[..],"voiceover":".."}
    script: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# LLM-facing strict variant of CopyOutput.
#
# `dict[str, Any]` fields collapse to a dummy `{"value": string}` object in the
# Gemini responseSchema, so the model physically cannot return slides/quiz/script
# in the shape the pipeline expects. Generation therefore uses these fully typed
# models and the result is converted back to the loose `CopyOutput`.
# --------------------------------------------------------------------------- #


class CarouselSlideSpec(BaseModel):
    index: int = 0
    title: str = ""
    body: str = ""
    bullets: list[str] = Field(default_factory=list)


class QuizSpec(BaseModel):
    question: str = ""
    answers: list[str] = Field(default_factory=list)
    correct_option_id: int = 0
    explanation: str = ""


class ReelsSceneSpec(BaseModel):
    t: str = Field(default="", description="Vaqt oralig'i, masalan '0-3s'")
    shot: str = ""
    on_screen: str = ""
    voice: str = ""


class ReelsScriptSpec(BaseModel):
    duration_sec: int = 30
    voiceover: str = ""
    scenes: list[ReelsSceneSpec] = Field(default_factory=list)


class CopyOutputStrict(BaseModel):
    headline: str = ""
    hook: str = ""
    caption_tg: str = ""
    caption_ig: str = ""
    cta: str = ""
    hashtags: list[str] = Field(default_factory=list)
    slides: list[CarouselSlideSpec] = Field(default_factory=list)
    quiz: QuizSpec = Field(default_factory=QuizSpec)
    script: ReelsScriptSpec = Field(default_factory=ReelsScriptSpec)

    def to_copy_output(self) -> CopyOutput:
        data = self.model_dump()
        if not data["quiz"]["answers"]:
            data["quiz"] = {}
        if not data["script"]["scenes"] and not data["script"]["voiceover"]:
            data["script"] = {}
        return CopyOutput(**data)


class EditorIssue(BaseModel):
    severity: str = "minor"          # critical | major | minor
    field: str = ""
    problem: str = ""
    suggestion: str = ""


class EditorOutput(BaseModel):
    approved: bool = True
    score: float = Field(default=0.0, ge=0.0, le=10.0)
    issues: list[EditorIssue] = Field(default_factory=list)
    fixed_caption_tg: str | None = None
    fixed_caption_ig: str | None = None
    summary: str = ""


class VoiceInstruction(BaseModel):
    """Parsed intent of a voice/text correction from the owner."""

    action: str = "edit_caption"      # edit_caption|change_price|reschedule|regenerate|change_image|reject|unknown
    target_field: str | None = None
    new_value: str | None = None
    new_datetime: datetime | None = None
    instruction_for_writer: str = ""
    confidence: float = 0.5


ContentPlanDetail.model_rebuild()
