"""The clip that goes out when the model does not.

The fallback used to be one business written down: "Til, matematika va IT",
"Ustozlar", "Har bir o'quvchiga alohida e'tibor". A bakery whose model call
failed published a language centre's clip.

Two things were worse than the wrong category. `"Sifatli ta'lim"` is the first
entry in this system's own banned-phrase list, and `"10 yil tajriba"` is an
invented number in a pipeline that forbids inventing numbers everywhere else —
the fallback was the one place nothing checked.

So the rules here are: say what the knowledge base actually holds, scaffold the
rest with words that cannot be false, and never state a figure nobody supplied.
"""

from __future__ import annotations

import pytest

from app.agents.kinetic import CLIP_FRAMES, GENERIC_FRAME, fallback_script, frame_for
from app.models.enums import BusinessCategory
from app.utils.text import find_empty_phrases
from tests.test_agents import make_business, make_knowledge


def business_of(category: BusinessCategory):
    business = make_business()
    business.category = category
    return business


def knowledge_with(*, usps=None, prices=None, offerings=None):
    knowledge = make_knowledge()
    knowledge.usps = usps or []
    knowledge.prices = prices or []
    knowledge.key_offerings = offerings or []
    return knowledge


def texts(scenes) -> str:
    """Every word the clip puts on screen."""
    return " ".join(f"{s.text} {s.sub} {s.value} {' '.join(s.items)}" for s in scenes)


# --------------------------------------------------------------------------- #
# The regressions this file exists for
# --------------------------------------------------------------------------- #
class TestNoEmptyPhrases:
    @pytest.mark.parametrize("category", list(BusinessCategory))
    def test_no_category_scaffolding_trips_the_banned_list(self, category):
        """The fallback used to open with the list's first entry verbatim."""
        for length in ("short", "long"):
            scenes = fallback_script("Mavzu", business_of(category), knowledge_with(), length)
            found = find_empty_phrases(texts(scenes))
            assert found == [], f"{category}/{length}: {found}"

    def test_the_old_lines_are_gone_from_the_fallback_machinery(self):
        """Scoped to the fallback itself.

        The prompt legitimately shows `"10 yil"` as an example of the stat
        scene's shape; what must not come back is a figure baked into the
        script the fallback actually emits.
        """
        import inspect

        from app.agents import kinetic

        source = inspect.getsource(kinetic.fallback_script) + repr(kinetic.CLIP_FRAMES)
        for line in ("Sifatli ta'lim", "10 yil", "Har bir o'quvchiga alohida e'tibor",
                     "Til, matematika va IT"):
            assert line not in source


class TestNoInventedNumbers:
    """A figure on screen must have come from the business, not from us."""

    def test_nothing_numeric_appears_when_nothing_is_known(self):
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.EDUCATION), knowledge_with(), "long")
        numbers = [s.value for s in scenes if s.kind == "stat"]
        assert numbers == [], f"invented: {numbers}"

    def test_a_chapter_number_is_not_a_claim(self):
        """`01`/`02` are section markers, not facts about the business."""
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.EDUCATION), knowledge_with(), "long")
        chapters = [s for s in scenes if s.kind == "chapter"]
        assert chapters and all(s.value.isdigit() for s in chapters)

    def test_a_real_price_does_become_a_stat(self):
        knowledge = knowledge_with(prices=[{"item": "Backend", "price": 800000, "currency": "UZS"}])
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.TECH), knowledge, "long")

        stats = [s for s in scenes if s.kind == "stat"]
        assert stats, "a supplied number is exactly what should be shown"
        assert any("800" in s.value for s in stats)


# --------------------------------------------------------------------------- #
# Knowledge first, scaffolding second
# --------------------------------------------------------------------------- #
class TestKnowledgeComesFirst:
    def test_a_usp_is_said_instead_of_the_category_line(self):
        knowledge = knowledge_with(usps=["Guruhda 6 kishi"])
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.EDUCATION), knowledge, "short")

        assert "Guruhda 6 kishi" in texts(scenes)

    def test_the_category_line_stands_in_when_nothing_is_known(self):
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.EDUCATION), knowledge_with(), "short")
        assert CLIP_FRAMES[BusinessCategory.EDUCATION].claim in texts(scenes)

    def test_an_offering_reaches_the_screen(self):
        knowledge = knowledge_with(offerings=[{"name": "Somsa"}])
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.FOOD_BEVERAGE), knowledge, "long")

        assert "Somsa" in texts(scenes)

    def test_a_bare_product_name_is_labelled(self):
        """"Somsa" alone is a word on a card; the noun says what it is."""
        knowledge = knowledge_with(offerings=[{"name": "Somsa"}])
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.FOOD_BEVERAGE), knowledge, "short")

        labelled = [s for s in scenes if s.text == "Somsa"]
        assert labelled and labelled[0].sub == "taom"

    def test_the_label_is_not_shown_next_to_a_question(self):
        """With no offering the slot holds the category question, not a product."""
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.FOOD_BEVERAGE), knowledge_with(), "short")
        assert all(s.sub != "taom" for s in scenes)

    def test_the_short_cut_says_what_is_sold(self):
        knowledge = knowledge_with(offerings=[{"name": "Somsa"}])
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.FOOD_BEVERAGE), knowledge, "short")
        assert "Somsa" in texts(scenes)

    def test_the_topic_always_opens_the_clip(self):
        scenes = fallback_script("Kuzgi qabul", business_of(BusinessCategory.EDUCATION), knowledge_with(), "short")
        assert scenes[0].text == "Kuzgi qabul"

    def test_an_empty_topic_does_not_produce_an_empty_first_scene(self):
        scenes = fallback_script("", business_of(BusinessCategory.EDUCATION), knowledge_with(), "short")
        assert scenes[0].text.strip()


class TestNothingIsSaidTwice:
    """A thin knowledge base used to leave one question on screen twice.

    In a 58-second clip that reads as a broken render, not a short one.
    """

    @pytest.mark.parametrize("category", list(BusinessCategory))
    def test_no_line_repeats_in_a_long_clip(self, category):
        scenes = fallback_script("Mavzu", business_of(category), knowledge_with(), "long")
        spoken = [s.text.strip() for s in scenes if s.kind == "text" and s.text.strip()]
        assert len(spoken) == len(set(spoken)), f"{category}: {spoken}"

    @pytest.mark.parametrize("category", list(BusinessCategory))
    def test_no_line_repeats_in_a_short_clip(self, category):
        scenes = fallback_script("Mavzu", business_of(category), knowledge_with(), "short")
        spoken = [s.text.strip() for s in scenes if s.kind == "text" and s.text.strip()]
        assert len(spoken) == len(set(spoken)), f"{category}: {spoken}"

    @pytest.mark.parametrize("category", list(BusinessCategory))
    def test_the_invitation_is_not_the_closing_reworded(self, category):
        """They land seconds apart, so near-identical reads as a stutter."""
        from app.utils.similarity import similarity

        frame = frame_for(category)
        assert similarity(frame.invitation, frame.closing) < 0.3, (
            f"{category}: {frame.invitation!r} vs {frame.closing!r}"
        )

    @pytest.mark.parametrize("category", list(BusinessCategory))
    def test_the_two_scaffolding_lines_differ(self, category):
        frame = frame_for(category)
        assert frame.claim.strip().lower() != frame.invitation.strip().lower()

    def test_the_prop_card_does_not_echo_a_chapter(self):
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.EDUCATION), knowledge_with(), "long")
        props = {s.text for s in scenes if s.kind == "prop"}
        chapters = {s.text for s in scenes if s.kind == "chapter"}
        assert props.isdisjoint(chapters)

    def test_a_usp_repeated_in_the_knowledge_base_is_said_once(self):
        knowledge = knowledge_with(usps=["Guruhda 6 kishi", "guruhda 6 kishi"])
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.EDUCATION), knowledge, "long")

        spoken = [s.text.strip().lower() for s in scenes if s.kind == "text"]
        assert spoken.count("guruhda 6 kishi") == 1

    def test_an_offering_that_is_also_a_usp_is_not_doubled(self):
        knowledge = knowledge_with(offerings=[{"name": "IELTS"}], usps=["IELTS"])
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.EDUCATION), knowledge, "long")

        spoken = [s.text.strip() for s in scenes if s.kind == "text"]
        assert spoken.count("IELTS") == 1


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #
class TestFrames:
    def test_every_category_is_mapped(self):
        for category in BusinessCategory:
            assert frame_for(category) is not None

    def test_a_bakery_and_a_language_centre_do_not_share_words(self):
        """The whole point: one client's clip is not every client's clip."""
        food = CLIP_FRAMES[BusinessCategory.FOOD_BEVERAGE]
        education = CLIP_FRAMES[BusinessCategory.EDUCATION]

        assert food.chapters != education.chapters
        assert food.claim != education.claim
        assert food.offering_word != education.offering_word

    def test_an_unknown_category_gets_the_generic_frame(self):
        assert frame_for(BusinessCategory.OTHER) is GENERIC_FRAME
        assert frame_for("nonsense") is GENERIC_FRAME  # type: ignore[arg-type]

    def test_ecommerce_and_retail_may_share_a_frame(self):
        """Same shelf, same clip — as in the shooting brief's catalogue."""
        assert frame_for(BusinessCategory.ECOMMERCE) is frame_for(BusinessCategory.RETAIL)


# --------------------------------------------------------------------------- #
# The structural contract the renderer depends on
# --------------------------------------------------------------------------- #
class TestShape:
    @pytest.mark.parametrize("category", list(BusinessCategory))
    def test_a_long_clip_has_enough_scenes_to_fill_its_runtime(self, category):
        """Stretched to ~58s at 3.4s a scene, so too few cannot be held."""
        scenes = fallback_script("Mavzu", business_of(category), knowledge_with(), "long")
        assert len(scenes) >= 8

    def test_a_long_clip_keeps_its_chapters(self):
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.BEAUTY), knowledge_with(), "long")
        assert sum(1 for s in scenes if s.kind == "chapter") >= 3

    def test_a_short_clip_stays_short(self):
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.BEAUTY), knowledge_with(), "short")
        assert 3 <= len(scenes) <= 6

    @pytest.mark.parametrize("category", list(BusinessCategory))
    def test_no_scene_is_blank(self, category):
        for length in ("short", "long"):
            for scene in fallback_script("Mavzu", business_of(category), knowledge_with(), length):
                assert (scene.text or scene.value).strip(), f"{category}/{length}: {scene}"

    def test_a_missing_knowledge_base_is_not_a_crash(self):
        scenes = fallback_script("Mavzu", business_of(BusinessCategory.RETAIL), None, "long")
        assert len(scenes) >= 8
