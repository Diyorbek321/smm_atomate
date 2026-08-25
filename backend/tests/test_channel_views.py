"""Reading our own reach back off the public channel page.

The Bot API hands over reactions and nothing else — no view count, ever. So
`prompt_templates.engagement_lift` has sat unwritten since the day it was
added: there was no number to put in it, and the analyst has been reasoning
about what worked from a column that is empty for every post.

Telegram's own public preview does give views, for our channel exactly as it
does for a competitor's. This is the collector that reads them back.

The other thing this file pins down is scoping. A Telegram message id is only
unique *within a channel*: Postchi's message 9 and a second client's message 9
are different posts, and a lookup by id alone will eventually write one
client's reach onto another's post.
"""

from __future__ import annotations

import pytest

from app.services.telegram_scout import ChannelSnapshot, ScoutPost
from app.tasks.metrics import message_id_of, views_by_message


def post(post_id: str, views: int) -> ScoutPost:
    return ScoutPost(handle="kanal", post_id=post_id, text="matn", views=views)


# --------------------------------------------------------------------------- #
class TestMessageId:
    """`data-post` is `<channel>/<message id>`; only the tail is the id."""

    def test_the_tail_is_the_id(self):
        assert message_id_of(post("postchi_uz/42", 100)) == "42"

    def test_a_handle_with_an_underscore_survives(self):
        assert message_id_of(post("my_long_channel/7", 100)) == "7"

    def test_a_bare_id_is_taken_as_is(self):
        assert message_id_of(post("42", 100)) == "42"

    def test_an_album_suffix_is_not_an_id(self):
        """Grouped media renders as `channel/12?single`; the id is still 12."""
        assert message_id_of(post("kanal/12?single", 100)) == "12"

    def test_nothing_usable(self):
        assert message_id_of(post("", 100)) is None
        assert message_id_of(post("kanal/", 100)) is None
        assert message_id_of(post("kanal/abc", 100)) is None


class TestViewsByMessage:
    def test_maps_id_to_views(self):
        snapshot = ChannelSnapshot(handle="kanal", posts=[post("kanal/8", 340), post("kanal/9", 512)])
        assert views_by_message(snapshot) == {"8": 340, "9": 512}

    def test_unmeasured_posts_are_left_out(self):
        """Zero is 'not counted yet', not 'nobody looked'."""
        snapshot = ChannelSnapshot(handle="kanal", posts=[post("kanal/8", 0), post("kanal/9", 512)])
        assert views_by_message(snapshot) == {"9": 512}

    def test_posts_without_an_id_are_skipped(self):
        snapshot = ChannelSnapshot(handle="kanal", posts=[post("", 340), post("kanal/9", 512)])
        assert views_by_message(snapshot) == {"9": 512}

    def test_an_empty_channel(self):
        assert views_by_message(ChannelSnapshot(handle="kanal")) == {}


# --------------------------------------------------------------------------- #
# Writing the number without losing what is already there
# --------------------------------------------------------------------------- #
class TestApply:
    @staticmethod
    def _item(metrics=None):
        class Item:
            def __init__(self):
                self.metrics = metrics if metrics is not None else {}
                self.tg_message_id = "9"
        return Item()

    def test_views_are_recorded(self):
        from app.tasks.metrics import apply_views

        item = self._item()
        assert apply_views(item, 512) is True
        assert item.metrics["views"] == 512

    def test_reactions_already_collected_are_not_lost(self):
        """Two different collectors write to the same JSON column."""
        from app.tasks.metrics import apply_views

        item = self._item({"reactions": 7, "reaction_breakdown": {"👍": 7}})
        apply_views(item, 512)

        assert item.metrics["views"] == 512
        assert item.metrics["reactions"] == 7
        assert item.metrics["reaction_breakdown"] == {"👍": 7}

    def test_a_view_count_that_has_not_moved_is_not_a_write(self):
        """Views only ever climb; rewriting the same number churns the row."""
        from app.tasks.metrics import apply_views

        item = self._item({"views": 512})
        assert apply_views(item, 512) is False

    def test_a_higher_count_replaces_the_old_one(self):
        from app.tasks.metrics import apply_views

        item = self._item({"views": 512})
        assert apply_views(item, 640) is True
        assert item.metrics["views"] == 640

    def test_a_lower_count_is_ignored(self):
        """Telegram rounds ("1.2K"), so a later read can parse smaller."""
        from app.tasks.metrics import apply_views

        item = self._item({"views": 1250})
        assert apply_views(item, 1200) is False
        assert item.metrics["views"] == 1250

    def test_the_reading_is_stamped(self):
        from app.tasks.metrics import apply_views

        item = self._item()
        apply_views(item, 512)
        assert item.metrics["views_at"]


# --------------------------------------------------------------------------- #
# Scoping — the bug this collector would otherwise introduce
# --------------------------------------------------------------------------- #
@pytest.mark.db
class TestScoping:
    """A message id is unique within a channel, never across them."""

    @staticmethod
    async def _business_with_post(session, name: str, message_ids: list[str]):
        """A business, a plan to hang items on, and one item per message id."""
        import uuid as _uuid
        from datetime import timedelta

        from app.models.business import Business
        from app.models.content_item import ContentItem
        from app.models.content_plan import ContentPlan
        from app.models.enums import (
            BusinessCategory,
            ContentItemStatus,
            ContentPillar,
            ContentPlanStatus,
            ContentType,
            Language,
        )
        from app.utils.dates import utcnow

        business = Business(
            name=name, slug=f"{name}-{_uuid.uuid4().hex[:8]}",
            category=BusinessCategory.EDUCATION, language=Language.UZ,
            timezone="Asia/Tashkent", settings={},
        )
        session.add(business)
        await session.flush()

        plan = ContentPlan(
            business_id=business.id, title=name, year=2026, week_number=34, month_number=8,
            starts_on=utcnow().date(), ends_on=utcnow().date() + timedelta(days=6),
            status=ContentPlanStatus.PENDING_REVIEW, strategy={}, notes="",
        )
        session.add(plan)
        await session.flush()

        for message_id in message_ids:
            session.add(ContentItem(
                business_id=business.id, content_plan_id=plan.id, topic=f"{name} posti",
                pillar=ContentPillar.EDUCATIONAL, content_type=ContentType.FEED_POST,
                status=ContentItemStatus.PUBLISHED, tg_message_id=message_id,
                scheduled_at=utcnow(),
            ))
        await session.flush()
        return business

    async def test_the_lookup_is_scoped_to_one_business(self, session):
        """Asks for the *second* business on purpose.

        An unscoped query returns whichever row the planner reaches first,
        which for the earlier-inserted business is usually the right answer by
        accident. Asking for the later one is what makes the filter load-bearing
        — and "usually right" is precisely what makes this class of bug survive
        review.
        """
        from app.repositories.content import ContentItemRepository

        await self._business_with_post(session, "bir", ["9"])
        two = await self._business_with_post(session, "ikki", ["9"])

        found = await ContentItemRepository(session).by_telegram_message("9", business_id=two.id)

        assert found is not None
        assert found.business_id == two.id, "another client's post must not match"

    async def test_an_unscoped_lookup_still_works_for_old_callers(self, session):
        from app.repositories.content import ContentItemRepository

        await self._business_with_post(session, "besh", ["77"])
        assert await ContentItemRepository(session).by_telegram_message("77") is not None

    async def test_the_batch_lookup_is_scoped_too(self, session):
        from app.repositories.content import ContentItemRepository

        one = await self._business_with_post(session, "uch", ["5", "6"])
        await self._business_with_post(session, "tort", ["5", "6"])

        rows = await ContentItemRepository(session).by_telegram_messages(one.id, ["5", "6"])

        assert len(rows) == 2
        assert {r.business_id for r in rows} == {one.id}

    async def test_an_empty_id_list_does_not_query(self, session):
        from app.repositories.content import ContentItemRepository

        assert await ContentItemRepository(session).by_telegram_messages(
            (await self._business_with_post(session, "olti", [])).id, []
        ) == []
