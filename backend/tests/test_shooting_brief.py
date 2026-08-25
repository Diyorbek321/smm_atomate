"""The monthly shot list — deterministic, personalised, and tier-aware."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.business import Business
from app.models.enums import BusinessCategory, Language, Plan, ToneOfVoice
from app.models.knowledge_base import KnowledgeBase
from app.services.shooting_brief import (
    CATALOGUES,
    EDUCATION,
    build_brief,
    catalogue_for,
    render_telegram,
)


def make_business(plan: Plan = Plan.PRO, category=BusinessCategory.EDUCATION) -> Business:
    return Business(
        name="Shanghai School",
        plan=plan,
        category=category,
        tone_of_voice=ToneOfVoice.CASUAL,
        target_audience="14-30",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={},
    )


def make_knowledge(**overrides) -> KnowledgeBase:
    knowledge = KnowledgeBase(
        key_offerings=[{"name": "IELTS intensiv"}],
        prices=[],
        usps=[],
        teacher_profiles=[{"name": "Nodira"}],
        faq=[],
        success_stories=[],
        banned_topics=[],
        preferred_hashtags=[],
        competitors=[],
        brand_colors={},
    )
    for key, value in overrides.items():
        setattr(knowledge, key, value)
    return knowledge


class TestBudget:
    @pytest.mark.parametrize(
        ("plan", "expected"),
        [(Plan.START, 6), (Plan.STANDARD, 10), (Plan.PRO, 14)],
    )
    def test_the_tier_decides_how_much_to_ask_for(self, plan: Plan, expected: int):
        """Ask a Start client for fourteen shots and they film none of them."""
        brief = build_brief(make_business(plan), make_knowledge(), date(2026, 9, 1))
        assert len(brief.shots) == expected

    def test_every_brief_carries_the_foundation(self):
        """Without a face, a room and the building most templates have no opening."""
        for plan in (Plan.START, Plan.STANDARD, Plan.PRO):
            keys = {s.key for s in build_brief(make_business(plan), make_knowledge()).shots}
            assert {shot.key for shot in EDUCATION.foundation} <= keys

    def test_a_start_client_is_still_asked_for_photographs(self):
        """No video in the plan does not mean no photo library."""
        brief = build_brief(make_business(Plan.START), make_knowledge())
        assert brief.photo_count >= 1


class TestRotation:
    def test_the_same_month_always_produces_the_same_brief(self):
        """The owner can be sent it twice without it changing under them."""
        first = build_brief(make_business(), make_knowledge(), date(2026, 9, 1))
        second = build_brief(make_business(), make_knowledge(), date(2026, 9, 1))
        assert [s.key for s in first.shots] == [s.key for s in second.shots]

    def test_consecutive_months_are_not_the_same_list(self):
        september = build_brief(make_business(), make_knowledge(), date(2026, 9, 1))
        october = build_brief(make_business(), make_knowledge(), date(2026, 10, 1))
        assert [s.key for s in september.shots] != [s.key for s in october.shots]

    def test_the_seasonal_shot_matches_the_month(self):
        for month in (1, 5, 9, 12):
            brief = build_brief(make_business(), make_knowledge(), date(2026, month, 1))
            assert EDUCATION.seasonal[month].key in {s.key for s in brief.shots}


class TestPersonalisation:
    def test_the_course_name_reaches_the_shot(self):
        brief = build_brief(make_business(), make_knowledge(), date(2026, 9, 1))
        assert any("IELTS intensiv" in shot.title for shot in brief.shots)

    def test_an_empty_knowledge_base_still_produces_a_usable_brief(self):
        knowledge = make_knowledge(key_offerings=[], teacher_profiles=[])
        brief = build_brief(make_business(), knowledge, date(2026, 9, 1))
        assert brief.shots
        assert not any("{course}" in shot.title for shot in brief.shots)

    def test_a_generic_fallback_does_not_repeat_itself_in_the_title(self):
        """«Ustoz o'zini tanishtiradi — ustoz» is worse than no suffix at all."""
        knowledge = make_knowledge(teacher_profiles=[])
        brief = build_brief(make_business(), knowledge, date(2026, 9, 1))
        assert not any("— ustoz" in shot.title.lower() for shot in brief.shots)

    def test_a_real_name_keeps_the_suffix(self):
        brief = build_brief(make_business(), make_knowledge(), date(2026, 9, 1))
        titles = " ".join(shot.title for shot in brief.shots)
        assert "Nodira" in titles

    def test_no_knowledge_base_at_all_does_not_crash(self):
        assert build_brief(make_business(), None, date(2026, 9, 1)).shots


class TestPerCategoryCatalogues:
    """The advice only helps when it is concrete, so each trade gets its own."""

    def test_a_restaurant_is_not_asked_about_classrooms(self):
        brief = build_brief(
            make_business(category=BusinessCategory.FOOD_BEVERAGE),
            make_knowledge(),
            date(2026, 9, 1),
        )
        keys = {s.key for s in brief.shots}
        assert "cooking" in keys
        assert "classroom" not in keys

    @pytest.mark.parametrize("category", list(BusinessCategory))
    def test_every_category_gets_a_full_brief(self, category: BusinessCategory):
        """A category with a thin catalogue would quietly hand out four shots."""
        brief = build_brief(make_business(category=category), make_knowledge(), date(2026, 9, 1))
        assert len(brief.shots) >= 10
        assert brief.photo_count >= 1
        assert brief.video_count >= 5

    @pytest.mark.parametrize("category", list(BusinessCategory))
    def test_no_placeholder_survives_into_a_brief(self, category: BusinessCategory):
        brief = build_brief(make_business(category=category), make_knowledge(), date(2026, 3, 1))
        for shot in brief.shots:
            assert "{" not in shot.title + shot.what + shot.how + shot.why

    def test_shot_keys_are_unique_within_a_catalogue(self):
        """A duplicate key would silently drop a shot from tracking later."""
        for category, catalogue in CATALOGUES.items():
            keys = [
                s.key
                for s in (*catalogue.foundation, *catalogue.proof, *catalogue.life,
                          *catalogue.seasonal.values())
            ]
            assert len(keys) == len(set(keys)), category

    def test_clinics_and_salons_carry_a_consent_warning(self):
        """Filming a patient or a before/after is not a casual decision."""
        for category in (BusinessCategory.HEALTHCARE, BusinessCategory.BEAUTY):
            brief = build_brief(make_business(category=category), make_knowledge())
            assert any("ruxsat" in note.lower() for note in brief.notes)

    def test_an_unmapped_category_falls_back_instead_of_failing(self):
        assert catalogue_for(BusinessCategory.OTHER).foundation


class TestRendering:
    def test_the_first_brief_says_so(self):
        brief = build_brief(make_business(), make_knowledge(), footage_on_hand=0)
        assert any("birinchi brif" in note for note in brief.notes)

    def test_the_telegram_text_lists_every_shot(self):
        brief = build_brief(make_business(), make_knowledge(), date(2026, 9, 1))
        text = render_telegram(brief)
        for shot in brief.shots:
            assert shot.title in text

    def test_the_telegram_text_opens_with_the_month(self):
        text = render_telegram(build_brief(make_business(), make_knowledge(), date(2026, 9, 1)))
        assert "Sentabr" in text.splitlines()[0]
