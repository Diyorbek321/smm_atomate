"""Enumerations shared by models, schemas, agents and publishers."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """`str` mixin enum so values serialise cleanly to JSON."""

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return str(self.value)

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


class Language(StrEnum):
    UZ = "uz"
    RU = "ru"
    EN = "en"


class ToneOfVoice(StrEnum):
    CASUAL = "casual"
    PROFESSIONAL = "professional"
    YOUTHFUL = "youthful"
    BOLD = "bold"
    HUMOROUS = "humorous"
    EXPERT = "expert"


class Plan(StrEnum):
    """Service tier the client pays for. See app/core/plans.py for the matrix."""

    START = "start"
    STANDARD = "standard"
    PRO = "pro"


class BusinessCategory(StrEnum):
    EDUCATION = "education"          # o'quv markaz — the primary target
    FOOD_BEVERAGE = "food_beverage"
    ECOMMERCE = "ecommerce"
    RETAIL = "retail"
    TECH = "tech"
    HEALTHCARE = "healthcare"
    REAL_ESTATE = "real_estate"
    BEAUTY = "beauty"
    OTHER = "other"


class ContentPillar(StrEnum):
    """Strategic buckets. Distribution is enforced by the StrategistAgent."""

    SALES = "sales"                  # 30%
    EDUCATIONAL = "educational"      # 30%
    SOCIAL_PROOF = "social_proof"    # 25%
    INTERACTIVE = "interactive"      # 15%


PILLAR_DISTRIBUTION: dict[ContentPillar, float] = {
    ContentPillar.SALES: 0.30,
    ContentPillar.EDUCATIONAL: 0.30,
    ContentPillar.SOCIAL_PROOF: 0.25,
    ContentPillar.INTERACTIVE: 0.15,
}


class ContentType(StrEnum):
    FEED_POST = "feed_post"
    CAROUSEL = "carousel"
    STORY = "story"
    TELEGRAM_QUIZ = "telegram_quiz"
    REELS_SCRIPT = "reels_script"
    #: Footage the owner shot, put through the editor. Never planned by the
    #: strategist — it only exists once a real video arrives.
    VIDEO_POST = "video_post"


#: Content types that make sense for each pillar (used when planning).
PILLAR_CONTENT_TYPES: dict[ContentPillar, list[ContentType]] = {
    ContentPillar.SALES: [ContentType.FEED_POST, ContentType.STORY, ContentType.CAROUSEL],
    ContentPillar.EDUCATIONAL: [ContentType.CAROUSEL, ContentType.FEED_POST, ContentType.REELS_SCRIPT],
    ContentPillar.SOCIAL_PROOF: [ContentType.FEED_POST, ContentType.STORY, ContentType.CAROUSEL],
    ContentPillar.INTERACTIVE: [ContentType.TELEGRAM_QUIZ, ContentType.STORY],
}


class ContentPlanStatus(StrEnum):
    DRAFT = "draft"
    GENERATING = "generating"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ContentItemStatus(StrEnum):
    DRAFT = "draft"
    GENERATING = "generating"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


#: Statuses that must never be mutated by the generator.
TERMINAL_ITEM_STATUSES = {ContentItemStatus.PUBLISHED, ContentItemStatus.REJECTED}


class Platform(StrEnum):
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"
    BOTH = "both"


class PublishState(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AdminRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    VIEWER = "viewer"


#: Which platforms a content type can be delivered to.
CONTENT_TYPE_PLATFORMS: dict[ContentType, list[Platform]] = {
    ContentType.FEED_POST: [Platform.TELEGRAM, Platform.INSTAGRAM],
    ContentType.CAROUSEL: [Platform.TELEGRAM, Platform.INSTAGRAM],
    ContentType.STORY: [Platform.TELEGRAM, Platform.INSTAGRAM],
    ContentType.TELEGRAM_QUIZ: [Platform.TELEGRAM],
    ContentType.REELS_SCRIPT: [Platform.TELEGRAM],
}
