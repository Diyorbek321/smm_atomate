"""The monthly report — the parts that hold without a database."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.models.business import Business
from app.models.content_item import ContentItem
from app.models.enums import (
    BusinessCategory,
    ContentPillar,
    ContentType,
    Language,
    Plan,
    Platform,
    ToneOfVoice,
)
from app.services.client_report import (
    ClientReport,
    TopPost,
    _gaps,
    _rank,
    _unmeasured,
    month_bounds,
    render_telegram,
)


def make_business(plan: Plan = Plan.PRO) -> Business:
    return Business(
        name="Shanghai School",
        plan=plan,
        category=BusinessCategory.EDUCATION,
        tone_of_voice=ToneOfVoice.CASUAL,
        target_audience="14-30",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={},
    )


def make_item(headline: str, *, reactions: int | None = None, day: int = 5) -> ContentItem:
    return ContentItem(
        business_id=uuid.uuid4(),
        content_type=ContentType.FEED_POST,
        pillar=ContentPillar.SALES,
        platform=Platform.TELEGRAM,
        topic=headline,
        headline=headline,
        scheduled_at=datetime(2026, 7, day, 10, 0),
        published_at=datetime(2026, 7, day, 10, 0),
        metrics={"reactions": reactions} if reactions is not None else {},
    )


class TestMonthBounds:
    def test_an_explicit_month_is_bounded_start_to_end(self):
        start, end = month_bounds(date(2026, 7, 15))
        assert start == datetime(2026, 7, 1, 0, 0)
        assert end.date() == date(2026, 7, 31)

    def test_december_rolls_into_the_next_year(self):
        start, end = month_bounds(date(2026, 12, 9))
        assert start == datetime(2026, 12, 1, 0, 0)
        assert end.date() == date(2026, 12, 31)

    def test_february_of_a_leap_year(self):
        _, end = month_bounds(date(2028, 2, 3))
        assert end.date() == date(2028, 2, 29)


class TestRanking:
    def test_measured_posts_outrank_unmeasured_ones(self):
        posts = [make_item("Sekin", reactions=2), make_item("Zo'r", reactions=40), make_item("Yo'q")]
        top = _rank(posts, "Asia/Tashkent")
        assert top[0].headline == "Zo'r"
        assert [p.headline for p in top][:2] == ["Zo'r", "Sekin"]

    def test_nothing_measured_still_returns_posts(self):
        """An empty «best posts» section reads as «nothing worked»."""
        top = _rank([make_item("Birinchi"), make_item("Ikkinchi", day=9)], "Asia/Tashkent")
        assert len(top) == 2
        assert all(p.reactions is None for p in top)

    def test_no_posts_gives_no_ranking(self):
        assert _rank([], "Asia/Tashkent") == []


class TestHonesty:
    def test_unmeasured_always_names_the_lead_attribution_gap(self):
        notes = _unmeasured(make_business(), [])
        assert any("qaysi postdan" in note for note in notes)

    def test_an_empty_media_shelf_is_reported_as_a_gap(self):
        gaps = _gaps(make_business(), [])
        assert any("Video kadr yuborilmadi" in gap for gap in gaps)
        assert any("haqiqiy surati yo'q" in gap for gap in gaps)

    def test_a_tier_without_instagram_says_so(self):
        assert any("Instagram tarifga kirmagan" in gap for gap in _gaps(make_business(Plan.START), []))

    def test_pro_does_not_get_the_instagram_gap(self):
        assert not any("Instagram tarifga" in gap for gap in _gaps(make_business(Plan.PRO), []))


class TestRendering:
    def _report(self, **overrides) -> ClientReport:
        report = ClientReport(
            business="Shanghai School",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            published_total=12,
            by_type={"post": 8, "karusel": 4},
            top_posts=[TopPost("Sentabr qabuli", "post", 41, date(2026, 7, 5))],
            leads_total=9,
            leads_new=3,
            leads_contacted=6,
            avg_quality=8.4,
            scheduled_next=7,
        )
        for key, value in overrides.items():
            setattr(report, key, value)
        return report

    def test_leads_come_before_content(self):
        """The client asked whether anyone came, not how much we produced."""
        text = render_telegram(self._report())
        assert text.index("Botga yozganlar") < text.index("Chiqarilgan kontent")

    def test_unanswered_leads_are_called_out(self):
        assert "javob kutyapti" in render_telegram(self._report())

    def test_a_month_with_no_leads_says_so_plainly(self):
        text = render_telegram(self._report(leads_total=0, leads_new=0, leads_contacted=0))
        assert "hech kim yozmadi" in text

    def test_the_period_label_is_a_month_name(self):
        assert "Iyul 2026" in render_telegram(self._report())

    def test_gaps_and_unmeasured_reach_the_message(self):
        text = render_telegram(
            self._report(gaps=["Video kadr yuborilmadi"], unmeasured=["Reaksiya yig'ilmagan"])
        )
        assert "Video kadr yuborilmadi" in text
        assert "Reaksiya yig'ilmagan" in text
