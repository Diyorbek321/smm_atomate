"""Service tiers and what each one is allowed to do.

One matrix, consulted everywhere: the strategist when it picks content types,
the visual agent before it renders video, the publisher before it touches
Instagram, and the bot before it answers a lead. A business may be granted a
single capability above its tier through ``settings["plan_overrides"]`` so a
client can be given a trial of something without being moved up a tier.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.core.config import settings
from app.models.enums import ContentPillar, ContentType, Plan

#: Capabilities that can be overridden per business (booleans only).
OVERRIDABLE = ("instagram", "video", "video_editing", "ai_video", "lead_autoreply")


@dataclass(frozen=True, slots=True)
class PlanCapabilities:
    """What a tier unlocks. Ceilings are inclusive."""

    max_posts_per_week: int
    content_types: frozenset[ContentType]
    instagram: bool
    video: bool           # rendered clips: story montage + kinetic typography
    video_editing: bool   # polishing footage the client shot themselves
    ai_video: bool        # paid generative video (fal.ai) — costs money per clip
    lead_autoreply: bool
    #: Which text-to-image model renders this tier's photos. The cheapest one
    #: is a 4-step distilled model — fine for a trial, visibly rough for a
    #: client whose feed this becomes. The price gap is a couple of cents.
    image_model: str = ""

    def allows(self, content_type: ContentType) -> bool:
        return content_type in self.content_types


PLAN_CAPABILITIES: dict[Plan, PlanCapabilities] = {
    Plan.START: PlanCapabilities(
        max_posts_per_week=4,
        content_types=frozenset({ContentType.FEED_POST, ContentType.TELEGRAM_QUIZ}),
        instagram=False,
        video=False,
        video_editing=False,
        ai_video=False,
        lead_autoreply=False,
        image_model=settings.fal_model_start,
    ),
    Plan.STANDARD: PlanCapabilities(
        max_posts_per_week=8,
        content_types=frozenset(
            {
                ContentType.FEED_POST,
                ContentType.CAROUSEL,
                ContentType.STORY,
                ContentType.TELEGRAM_QUIZ,
                ContentType.VIDEO_POST,
            }
        ),
        instagram=True,
        video=False,
        video_editing=True,
        ai_video=False,
        lead_autoreply=False,
        image_model=settings.fal_model_standard,
    ),
    Plan.PRO: PlanCapabilities(
        max_posts_per_week=20,
        content_types=frozenset(ContentType),
        instagram=True,
        video=True,
        video_editing=True,
        ai_video=True,
        lead_autoreply=True,
        image_model=settings.fal_model_pro,
    ),
}

#: Every tier can always fall back to this, so a plan can never end up empty.
BASELINE_CONTENT_TYPE = ContentType.FEED_POST


def capabilities_for(plan: Plan | str, overrides: dict[str, Any] | None = None) -> PlanCapabilities:
    """Return the tier's capabilities, with per-business grants applied."""
    try:
        tier = Plan(plan)
    except ValueError:
        tier = Plan.START
    capabilities = PLAN_CAPABILITIES[tier]

    if not overrides:
        return capabilities

    granted = {
        key: bool(overrides[key])
        for key in OVERRIDABLE
        if key in overrides and overrides[key] is not None
    }
    return replace(capabilities, **granted) if granted else capabilities


def pillar_content_types(capabilities: PlanCapabilities) -> dict[ContentPillar, list[ContentType]]:
    """`PILLAR_CONTENT_TYPES` narrowed to what the tier unlocks.

    A pillar never comes back empty — if the tier locks every type the pillar
    would normally use, it falls back to a plain feed post.
    """
    from app.models.enums import PILLAR_CONTENT_TYPES

    narrowed: dict[ContentPillar, list[ContentType]] = {}
    for pillar, types in PILLAR_CONTENT_TYPES.items():
        allowed = [t for t in types if capabilities.allows(t)]
        narrowed[pillar] = allowed or [BASELINE_CONTENT_TYPE]
    return narrowed
