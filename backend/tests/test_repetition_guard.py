"""Why the same five topics came back every week, and what now stops them.

The pipeline had a memory, three checks that used it, and a filter in front of
all of them that let almost nothing through: only *published* posts counted as
history. On an account that reviews before publishing — which is every account
by default — that meant the planner woke up each run having forgotten the plan
it wrote on Tuesday and the owner rejected on Wednesday, and proposed it again.

These lock each link of that chain.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import ClassVar

import pytest

from app.agents.copywriter import HISTORY_LINES, CopywriterAgent
from app.agents.marketolog import MarketologAgent
from app.agents.strategist import _performance_block


class TestPlannerSeesUnpublishedHistory:
    """The bug: `published: 0` blanked the whole block, memory included."""

    DRAFTS_ONLY: ClassVar[dict] = {
        "published": 0,
        "by_pillar": {},
        "recent_topics": ["STANDARD tarif tarkibi", "Postchi qanday ishlaydi"],
        "rejected_topics": ["STANDARD tarif tarkibi"],
    }

    def test_topics_survive_when_nothing_was_ever_published(self):
        block = _performance_block(self.DRAFTS_ONLY)
        assert "STANDARD tarif tarkibi" in block
        assert "Postchi qanday ishlaydi" in block

    def test_no_numbers_are_invented_for_an_account_with_none(self):
        """Covered ground is a fact; a track record would be fiction."""
        block = _performance_block(self.DRAFTS_ONLY)
        assert "OXIRGI 60 KUN" not in block
        assert "reaksiya" not in block

    def test_a_rejected_topic_is_stated_harder_than_a_covered_one(self):
        block = _performance_block(self.DRAFTS_ONLY)
        assert "RAD ETGAN" in block
        assert block.index("ALLAQACHON") < block.index("RAD ETGAN")

    def test_truly_empty_history_still_says_nothing(self):
        assert _performance_block({}) == ""
        assert _performance_block({"published": 0, "by_pillar": {}}) == ""

    def test_numbers_and_topics_appear_together_once_posts_go_out(self):
        block = _performance_block(
            {
                "published": 6,
                "by_pillar": {"sales": {"posts": 6, "measured": 6, "avg_reactions": 3.0}},
                "recent_topics": ["START tarif imkoniyatlari"],
                "rejected_topics": [],
            }
        )
        assert "OXIRGI 60 KUN" in block and "START tarif imkoniyatlari" in block


class TestMarketologSeesUnpublishedHistory:
    """Same filter, same fix, one layer up: the week's commercial angle."""

    def test_topics_are_briefed_even_with_nothing_published(self):
        block = MarketologAgent._performance_block(
            {"published": 0, "recent_topics": ["PRO tarif afzalliklari"], "rejected_topics": []}
        )
        assert "hali e'lon qilingan post yo'q" in block
        assert "PRO tarif afzalliklari" in block

    def test_owner_rejections_reach_the_brief(self):
        block = MarketologAgent._performance_block(
            {"published": 0, "recent_topics": ["Mijoz bilan ishlash"], "rejected_topics": ["Mijoz bilan ishlash"]}
        )
        assert "RAD ETGAN" in block

    def test_an_account_with_no_history_at_all_is_unchanged(self):
        block = MarketologAgent._performance_block({})
        assert "hali e'lon qilingan post yo'q" in block
        assert "RAD ETGAN" not in block


class TestWriterSeesWhatItAlreadyWrote:
    """`previous_caption` covered one rewrite. Nothing covered the month."""

    def test_past_headlines_are_put_in_front_of_the_writer(self):
        block = CopywriterAgent._history_block(
            ["Postchi qanday ishlaydi: 4 daqiqada 16 ta post", "START tarif imkoniyatlari"]
        )
        assert "Postchi qanday ishlaydi" in block
        assert "takrorlama" in block

    def test_nothing_written_yet_adds_no_block(self):
        assert CopywriterAgent._history_block([]) == ""
        assert CopywriterAgent._history_block(["", "   "]) == ""

    def test_repeats_are_shown_once(self):
        block = CopywriterAgent._history_block(["Bir xil sarlavha", "bir xil sarlavha"])
        assert block.count("ir xil sarlavha") == 1

    def test_the_block_stays_short_enough_not_to_crowd_the_brief(self):
        block = CopywriterAgent._history_block([f"Sarlavha raqami {i}" for i in range(40)])
        assert len([line for line in block.splitlines() if line.startswith("- ")]) == HISTORY_LINES

    def test_a_long_headline_is_trimmed_not_dropped(self):
        block = CopywriterAgent._history_block(["x" * 300])
        entries = [line for line in block.splitlines() if line.startswith("- ")]
        assert entries and len(entries[0]) < 120


class TestPlanDoesNotRepeatItself:
    """Two slots, one subject, both survived the exact-match filter."""

    def _enforce(self, topics: list[str]):
        from app.agents.strategist import StrategistAgent, StrategyRequest
        from app.models.enums import ContentPillar, ContentType, Platform
        from app.schemas.content import PlanSlot
        from tests.test_agents import make_business

        business = make_business()
        request = StrategyRequest(
            business=business, knowledge=None, starts_on=date(2026, 9, 1), posts_count=len(topics)
        )
        allocation = {ContentPillar.SALES: len(topics)}
        slots = [
            PlanSlot(
                day_offset=index,
                hour=9,
                pillar=ContentPillar.SALES,
                content_type=ContentType.FEED_POST,
                topic=topic,
                platform=Platform.BOTH,
            )
            for index, topic in enumerate(topics)
        ]
        blueprint = list(slots)
        agent = StrategistAgent.__new__(StrategistAgent)
        return agent._enforce(slots, allocation, blueprint, request)

    def test_a_reworded_topic_is_not_a_second_slot(self):
        final = self._enforce(
            ["STANDARD tarif tarkibi", "STANDARD tarif tarkibi va imkoniyatlari"]
        )
        assert len({slot.topic for slot in final}) == 1

    def test_genuinely_different_topics_both_survive(self):
        final = self._enforce(["STANDARD tarif tarkibi", "Klinikalar uchun kadr yo'riqnomasi"])
        assert len({slot.topic for slot in final}) == 2


class TestHistoryWithinOneRun:
    """A plan is eight posts written against one snapshot of the past.

    The snapshot is taken before any of them exist, so until now nothing
    stopped slot six from repeating slot two, and a regenerated post was
    compared against its own row in the history table.
    """

    def _pipeline(self):
        from app.agents.orchestrator import ContentPipeline

        return ContentPipeline(None)   # type: ignore[arg-type]

    def _slot(self, topic: str):
        from app.models.enums import ContentPillar, ContentType, Platform
        from app.schemas.content import PlanSlot

        return PlanSlot(
            day_offset=0,
            hour=9,
            pillar=ContentPillar.SALES,
            content_type=ContentType.FEED_POST,
            topic=topic,
            platform=Platform.BOTH,
        )

    def test_a_slot_is_visible_to_the_slots_after_it(self):
        from app.schemas.content import CopyOutput
        from tests.test_agents import make_business

        pipeline, business = self._pipeline(), make_business()
        pipeline._recent_subjects[business.id] = []
        pipeline._remember_subject(
            business, CopyOutput(headline="START tarif imkoniyatlari"), self._slot("START tarif")
        )
        assert ("START tarif imkoniyatlari", "START tarif") in pipeline._recent_subjects[business.id]

    def test_the_same_post_is_recorded_once(self):
        from app.schemas.content import CopyOutput
        from tests.test_agents import make_business

        pipeline, business = self._pipeline(), make_business()
        for _ in range(3):
            pipeline._remember_subject(
                business, CopyOutput(headline="Bir xil"), self._slot("Bir xil mavzu")
            )
        assert len(pipeline._recent_subjects[business.id]) == 1

    def test_an_empty_draft_is_not_recorded(self):
        from app.schemas.content import CopyOutput
        from tests.test_agents import make_business

        pipeline, business = self._pipeline(), make_business()
        pipeline._remember_subject(business, CopyOutput(headline="  "), self._slot("  "))
        assert pipeline._recent_subjects[business.id] == []

    def test_a_rewrite_replaces_the_version_it_supersedes(self):
        """Otherwise the old headline lingers and the *next* rewrite, excluded
        only by the current one, is reported as a duplicate of itself."""
        from app.schemas.content import CopyOutput
        from tests.test_agents import make_business

        pipeline, business = self._pipeline(), make_business()
        first = ("Birinchi variant", "START tarif")
        pipeline._recent_subjects[business.id] = [first]

        pipeline._remember_subject(
            business, CopyOutput(headline="Ikkinchi variant"), self._slot("START tarif"),
            replaces=first,
        )
        assert pipeline._recent_subjects[business.id] == [("Ikkinchi variant", "START tarif")]

    async def test_a_rewrite_is_not_a_duplicate_of_the_post_it_rewrites(self):
        from tests.test_agents import make_business

        pipeline, business = self._pipeline(), make_business()
        own = ("START tarif imkoniyatlari", "START tarif")
        pipeline._recent_subjects[business.id] = [own, ("Boshqa post", "Boshqa mavzu")]

        history = await pipeline._recent_history(business, exclude=own)
        assert own not in history
        assert ("Boshqa post", "Boshqa mavzu") in history

    async def test_excluding_one_post_does_not_erase_it_from_the_cache(self):
        """The next slot in the same run still has to see it."""
        from tests.test_agents import make_business

        pipeline, business = self._pipeline(), make_business()
        own = ("START tarif imkoniyatlari", "START tarif")
        pipeline._recent_subjects[business.id] = [own]

        await pipeline._recent_history(business, exclude=own)
        assert pipeline._recent_subjects[business.id] == [own]

    def test_the_writer_is_handed_headlines_not_pairs(self):
        from app.agents.orchestrator import ContentPipeline

        lines = ContentPipeline._headline_lines([("Sarlavha", "mavzu"), ("", "faqat mavzu")])
        assert lines == ["Sarlavha"]


@pytest.mark.db
class TestHistoryQuery:
    """`recent_performance` is where the published-only filter actually lived."""

    async def _seed(self, session, business_id, rows):
        from app.models.content_item import ContentItem
        from app.models.enums import ContentPillar, ContentType, Platform
        from app.utils.dates import utcnow

        for topic, status, notes in rows:
            session.add(
                ContentItem(
                    business_id=business_id,
                    content_type=ContentType.FEED_POST,
                    pillar=ContentPillar.SALES,
                    platform=Platform.TELEGRAM,
                    topic=topic,
                    headline=topic,
                    caption_tg="matn",
                    caption_ig="matn",
                    scheduled_at=utcnow(),
                    status=status,
                    review_notes=notes,
                )
            )
        await session.flush()

    async def test_drafts_and_rejections_count_as_covered_ground(self, session, client, business_payload):
        from app.models.content_item import SUPERSEDED_NOTE
        from app.models.enums import ContentItemStatus
        from app.repositories.content import ContentItemRepository

        created = await client.post("/api/v1/businesses", json=business_payload)
        business_id = uuid.UUID(created.json()["data"]["id"])
        await self._seed(
            session,
            business_id,
            [
                ("Ko'rikda turgan mavzu", ContentItemStatus.PENDING_REVIEW, ""),
                ("Ega rad etgan mavzu", ContentItemStatus.REJECTED, "bu mavzu menga yoqmadi"),
                ("Almashtirilgan mavzu", ContentItemStatus.REJECTED, SUPERSEDED_NOTE),
            ],
        )

        performance = await ContentItemRepository(session).recent_performance(business_id)

        assert performance["published"] == 0
        assert set(performance["recent_topics"]) == {
            "Ko'rikda turgan mavzu",
            "Ega rad etgan mavzu",
            "Almashtirilgan mavzu",
        }

    async def test_only_a_real_rejection_counts_as_feedback(self, session, client, business_payload):
        """Regenerating a plan retires its drafts by rejecting them. That is
        bookkeeping, not the owner saying no, and briefing it as a ban would
        forbid topics nobody ever objected to."""
        from app.models.content_item import SUPERSEDED_NOTE
        from app.models.enums import ContentItemStatus
        from app.repositories.content import ContentItemRepository

        created = await client.post("/api/v1/businesses", json=business_payload)
        business_id = uuid.UUID(created.json()["data"]["id"])
        await self._seed(
            session,
            business_id,
            [
                ("Ega rad etgan mavzu", ContentItemStatus.REJECTED, "bu mavzu menga yoqmadi"),
                ("Almashtirilgan mavzu", ContentItemStatus.REJECTED, SUPERSEDED_NOTE),
            ],
        )

        performance = await ContentItemRepository(session).recent_performance(business_id)
        assert performance["rejected_topics"] == ["Ega rad etgan mavzu"]

    async def test_subjects_keep_headline_and_topic_apart(self, session, client, business_payload):
        from app.models.enums import ContentItemStatus
        from app.repositories.content import ContentItemRepository

        created = await client.post("/api/v1/businesses", json=business_payload)
        business_id = uuid.UUID(created.json()["data"]["id"])
        await self._seed(session, business_id, [("Mavzu", ContentItemStatus.PENDING_REVIEW, "")])

        subjects = await ContentItemRepository(session).recent_subjects(business_id)
        assert subjects == [("Mavzu", "Mavzu")]
