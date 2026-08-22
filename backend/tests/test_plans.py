"""Service tiers: the matrix itself, and the places that enforce it."""

from __future__ import annotations

import pytest

from app.core.plans import (
    BASELINE_CONTENT_TYPE,
    PLAN_CAPABILITIES,
    capabilities_for,
    pillar_content_types,
)
from app.models.business import Business
from app.models.enums import ContentPillar, ContentType, Plan


def business(plan: Plan, **settings) -> Business:
    return Business(name="Client", plan=plan, settings=settings)


class TestMatrix:
    def test_every_tier_is_defined(self):
        assert set(PLAN_CAPABILITIES) == set(Plan)

    def test_tiers_are_strictly_increasing(self):
        start, standard, pro = (PLAN_CAPABILITIES[p] for p in (Plan.START, Plan.STANDARD, Plan.PRO))
        assert start.max_posts_per_week < standard.max_posts_per_week < pro.max_posts_per_week
        assert start.content_types < standard.content_types < pro.content_types
        assert not start.instagram and standard.instagram and pro.instagram
        assert not standard.video and pro.video

    def test_pro_unlocks_every_content_type(self):
        assert PLAN_CAPABILITIES[Plan.PRO].content_types == frozenset(ContentType)

    def test_paid_video_is_pro_only(self):
        assert [p for p in Plan if PLAN_CAPABILITIES[p].ai_video] == [Plan.PRO]

    def test_unknown_plan_fails_closed(self):
        assert capabilities_for("enterprise") == PLAN_CAPABILITIES[Plan.START]
        assert capabilities_for(None) == PLAN_CAPABILITIES[Plan.START]


class TestOverrides:
    def test_single_capability_can_be_granted(self):
        granted = capabilities_for(Plan.START, {"video": True})
        assert granted.video is True
        assert granted.instagram is False              # nothing else moves
        assert granted.max_posts_per_week == 4         # ceilings are not overridable

    def test_capability_can_be_revoked(self):
        assert capabilities_for(Plan.PRO, {"ai_video": False}).ai_video is False

    def test_unknown_and_empty_overrides_are_ignored(self):
        base = PLAN_CAPABILITIES[Plan.STANDARD]
        assert capabilities_for(Plan.STANDARD, {"teleport": True}) == base
        assert capabilities_for(Plan.STANDARD, {}) == base
        assert capabilities_for(Plan.STANDARD, {"video": None}) == base


class TestPillarNarrowing:
    @pytest.mark.parametrize("plan", list(Plan))
    def test_no_pillar_is_ever_left_empty(self, plan):
        narrowed = pillar_content_types(PLAN_CAPABILITIES[plan])
        assert set(narrowed) == set(ContentPillar)
        assert all(types for types in narrowed.values())

    def test_start_falls_back_to_a_plain_post(self):
        narrowed = pillar_content_types(PLAN_CAPABILITIES[Plan.START])
        assert narrowed[ContentPillar.EDUCATIONAL] == [BASELINE_CONTENT_TYPE]
        assert narrowed[ContentPillar.INTERACTIVE] == [ContentType.TELEGRAM_QUIZ]

    @pytest.mark.parametrize("plan", list(Plan))
    def test_narrowing_never_leaks_a_locked_type(self, plan):
        capabilities = PLAN_CAPABILITIES[plan]
        for types in pillar_content_types(capabilities).values():
            assert all(capabilities.allows(t) for t in types if t != BASELINE_CONTENT_TYPE)


class TestBusinessModel:
    def test_weekly_volume_is_capped_by_the_tier(self):
        assert business(Plan.START, posts_per_week=30).posts_per_week == 4
        assert business(Plan.STANDARD, posts_per_week=30).posts_per_week == 8
        assert business(Plan.PRO, posts_per_week=30).posts_per_week == 20

    def test_a_modest_request_is_left_alone(self):
        assert business(Plan.PRO, posts_per_week=6).posts_per_week == 6

    def test_floor_still_applies(self):
        assert business(Plan.PRO, posts_per_week=1).posts_per_week == 4

    def test_overrides_reach_the_model(self):
        client = business(Plan.START, plan_overrides={"lead_autoreply": True})
        assert client.capabilities.lead_autoreply is True


class TestStrategistRespectsThePlan:
    """The plan skeleton is deterministic, so it can be asserted directly."""

    def _slots(self, plan: Plan, posts: int = 8):
        from app.agents.strategist import StrategistAgent, StrategyRequest, allocate_pillars
        from app.agents.strategist import pillar_ratios_for
        from datetime import date

        client = business(plan, posts_per_week=posts)
        request = StrategyRequest(
            business=client, knowledge=None, starts_on=date(2026, 8, 24), posts_count=posts
        )
        allocation = allocate_pillars(posts, pillar_ratios_for(client))
        return StrategistAgent()._blueprint(allocation, request), client

    def test_start_plans_only_posts_and_quizzes(self):
        slots, client = self._slots(Plan.START)
        produced = {slot.content_type for slot in slots}
        assert produced <= client.capabilities.content_types
        assert ContentType.CAROUSEL not in produced
        assert ContentType.REELS_SCRIPT not in produced

    def test_standard_plans_carousels_but_no_reels(self):
        slots, client = self._slots(Plan.STANDARD)
        produced = {slot.content_type for slot in slots}
        assert produced <= client.capabilities.content_types
        assert ContentType.REELS_SCRIPT not in produced

    def test_pro_may_use_reels(self):
        slots, _ = self._slots(Plan.PRO, posts=20)
        assert ContentType.REELS_SCRIPT in {slot.content_type for slot in slots}

    @pytest.mark.parametrize("plan", list(Plan))
    def test_the_prompt_only_offers_allowed_types(self, plan):
        from app.agents.strategist import StrategistAgent, StrategyRequest, allocate_pillars
        from app.agents.strategist import pillar_ratios_for
        from datetime import date

        client = business(plan, posts_per_week=8)
        request = StrategyRequest(
            business=client, knowledge=None, starts_on=date(2026, 8, 24), posts_count=8
        )
        allocation = allocate_pillars(8, pillar_ratios_for(client))
        agent = StrategistAgent()
        prompt = agent._build_prompt(request, allocation, agent._blueprint(allocation, request))

        locked = {t.value for t in ContentType} - {t.value for t in client.capabilities.content_types}
        offered = prompt.split("RUXSAT ETILGAN content_type LAR:")[1].split("\n\n")[0]
        assert not [name for name in locked if name in offered]

    def test_llm_slots_outside_the_plan_are_repaired(self):
        from app.agents.strategist import StrategistAgent, StrategyRequest, allocate_pillars
        from app.agents.strategist import pillar_ratios_for
        from app.schemas.content import PlanSlot
        from datetime import date

        client = business(Plan.START, posts_per_week=4)
        request = StrategyRequest(
            business=client, knowledge=None, starts_on=date(2026, 8, 24), posts_count=4
        )
        allocation = allocate_pillars(4, pillar_ratios_for(client))
        agent = StrategistAgent()
        blueprint = agent._blueprint(allocation, request)

        # An LLM that ignores the brief and asks for Pro-only formats.
        rogue = [
            PlanSlot(
                day_offset=index,
                hour=9,
                pillar=slot.pillar,
                content_type=ContentType.REELS_SCRIPT,
                topic=f"mavzu {index}",
                angle="",
                goal="",
            )
            for index, slot in enumerate(blueprint)
        ]
        repaired = agent._enforce(rogue, allocation, blueprint, request)

        assert repaired
        assert all(slot.content_type in client.capabilities.content_types for slot in repaired)


class TestPublisherRespectsThePlan:
    async def test_instagram_is_skipped_below_standard(self):
        from app.models.enums import PublishState
        from app.services.publisher import PublishingService

        item = _item()
        outcome = await PublishingService(session=None)._instagram(item, business(Plan.START), None)

        assert outcome.state == PublishState.SKIPPED
        assert "start" in outcome.message
        assert outcome.retryable is False

    async def test_standard_reaches_the_credentials_check(self):
        """Not blocked by the tier any more — blocked by missing tokens."""
        from app.models.enums import PublishState
        from app.services.publisher import PublishingService

        item = _item()
        outcome = await PublishingService(session=None)._instagram(item, business(Plan.STANDARD), None)

        assert outcome.state == PublishState.SKIPPED
        assert outcome.message == "instagram not configured"

    async def test_a_granted_override_unlocks_the_channel(self):
        from app.services.publisher import PublishingService

        client = business(Plan.START, plan_overrides={"instagram": True})
        outcome = await PublishingService(session=None)._instagram(_item(), client, None)

        assert outcome.message == "instagram not configured"   # tier no longer the blocker


class TestVisualRespectsThePlan:
    async def test_video_is_not_rendered_below_pro(self):
        from app.agents.visual import VisualAgent, VisualRequest

        request = VisualRequest(
            business=business(Plan.STANDARD),
            knowledge=None,
            content_type=ContentType.STORY,
            pillar=ContentPillar.SALES,
            topic="Kuzgi qabul",
        )
        assert await VisualAgent()._render_video(request, _brief()) is None

    async def test_paid_clips_need_both_the_tier_and_the_switch(self):
        """`ai_video` costs money — the tier alone must not be enough."""
        assert business(Plan.PRO).capabilities.ai_video is True
        assert (business(Plan.PRO).settings or {}).get("ai_video") is None
        assert business(Plan.STANDARD, ai_video=True).capabilities.ai_video is False


def _item():
    from app.models.content_item import ContentItem
    from app.models.enums import ContentType as CT, ContentPillar as CP, Platform

    return ContentItem(
        business_id=None,
        content_type=CT.FEED_POST,
        pillar=CP.SALES,
        platform=Platform.BOTH,
        topic="t",
        headline="h",
        hook="",
        cta="",
        caption_tg="matn",
        caption_ig="matn",
    )


def _brief():
    from app.agents.visual import VisualBrief

    return VisualBrief(card_text="Kuzgi qabul")
