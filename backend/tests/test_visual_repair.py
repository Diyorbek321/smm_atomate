"""Choosing the next attempt from what the reviewer actually complained about.

The gate always worked; the repair did not. Every rejected card got the same
remedy — shorten the headline — because the attempts were built before any
verdict existed. A card broken by a font that renders its glyphs on top of each
other was handed "fewer words", twice, and shipped broken anyway.

So the reviewer's own verdict picks the lever now. Each lever is pulled at most
once, which is what stops the loop from spending a second render re-trying a
remedy that has already failed.
"""

from __future__ import annotations

import pytest

from app.services.visual_qc import VisualVerdict
from app.services.visual_repair import ARTEFACT, CLIPPED, CONTRAST, LAYOUT, diagnose, repair


def verdict(score: int = 3, *, complete: bool = True, readable: bool = True, issues=None):
    return VisualVerdict(
        score=score, text_complete=complete, readable=readable, issues=issues or []
    )


def context(**over):
    base = {
        "title": "SMM uchun freelancer yoki tizim: qaysi biri samaraliroq?",
        "body": "Odam ishini sistemaga topshiring.",
        "photo": "data:image/jpeg;base64,AAAA",
        "layout": {"title_size": 88, "body_size": 36, "padding": 80},
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Reading the complaint
# --------------------------------------------------------------------------- #
class TestDiagnose:
    """The booleans are the reviewer's own structured answer — trust them first."""

    def test_incomplete_text_is_a_clipping_problem(self):
        assert diagnose(verdict(complete=False)) == CLIPPED

    def test_unreadable_is_a_contrast_problem(self):
        assert diagnose(verdict(readable=False)) == CONTRAST

    def test_clipping_outranks_contrast_when_both_are_flagged(self):
        """A clipped headline is the louder defect and the cheaper fix."""
        assert diagnose(verdict(complete=False, readable=False)) == CLIPPED

    @pytest.mark.parametrize(
        "issue",
        [
            "Asosiy sarlavha matni kadr chetiga juda yaqin va qisman kesilgan.",
            "Matnning o'ng tomoni dizayn chegarasidan chiqib ketgan.",
            "Sarlavha to'liq sig'magan.",
            "Harflar ustma-ust tushgan.",
        ],
    )
    def test_the_wording_of_a_clipping_complaint(self, issue):
        assert diagnose(verdict(issues=[issue])) == CLIPPED

    @pytest.mark.parametrize(
        "issue",
        ["Matn fon bilan qo'shilib ketgan, kontrast past.", "Yozuv deyarli ko'rinmayapti."],
    )
    def test_the_wording_of_a_contrast_complaint(self, issue):
        assert diagnose(verdict(issues=[issue])) == CONTRAST

    @pytest.mark.parametrize(
        "issue",
        [
            "Rasmdagi odamning qo'li buzuq chiqqan.",
            "Fonda ma'nosiz harflar bor.",
            "Yuz g'alati ko'rinadi.",
        ],
    )
    def test_the_wording_of_an_image_complaint(self, issue):
        assert diagnose(verdict(issues=[issue])) == ARTEFACT

    def test_an_unlabelled_complaint_falls_back_to_layout(self):
        assert diagnose(verdict(issues=["Umuman zaif ko'rinadi."])) == LAYOUT

    def test_no_complaint_at_all(self):
        assert diagnose(verdict(issues=[])) == LAYOUT

    def test_apostrophe_spelling_does_not_change_the_reading(self):
        """The same word arrives as o' / o‘ / oʻ depending on the keyboard."""
        for form in ("chiqib ketgan", "chiqib ketgan"):
            assert diagnose(verdict(issues=[f"Matn chegaradan {form}."])) == CLIPPED


# --------------------------------------------------------------------------- #
# Pulling the lever
# --------------------------------------------------------------------------- #
class TestRepair:
    def test_a_clipped_card_gets_smaller_type_before_fewer_words(self):
        """Shrinking keeps the copy the editor approved; truncating loses it."""
        fixed = repair(context(), verdict(complete=False), tried=set())

        assert fixed is not None
        assert fixed["layout"]["title_size"] < 88
        assert fixed["title"] == context()["title"], "the words survive the first repair"

    def test_the_second_clipping_repair_drops_words(self):
        fixed = repair(context(), verdict(complete=False), tried={CLIPPED})

        assert fixed is not None
        assert len(fixed["title"]) < len(context()["title"])

    def test_a_contrast_problem_removes_the_photo(self):
        """The drawn canvas has a scrim we control; a photo does not."""
        fixed = repair(context(), verdict(readable=False), tried=set())

        assert fixed is not None
        assert fixed["photo"] == ""

    def test_an_image_artefact_removes_the_photo(self):
        fixed = repair(context(), verdict(issues=["Fonda ma'nosiz harflar bor."]), tried=set())

        assert fixed is not None
        assert fixed["photo"] == ""

    def test_a_layout_problem_drops_the_supporting_line(self):
        fixed = repair(context(), verdict(issues=["Bo'sh joy muvozanatsiz."]), tried=set())

        assert fixed is not None
        assert fixed["body"] == ""

    def test_the_original_context_is_never_mutated(self):
        original = context()
        repair(original, verdict(complete=False), tried=set())

        assert original["layout"]["title_size"] == 88
        assert original["body"] != ""

    def test_a_lever_already_pulled_is_not_pulled_again(self):
        """Every repair tried and still failing means there is nothing left."""
        assert repair(context(), verdict(readable=False), tried={CONTRAST}) is None

    def test_a_photo_repair_on_a_card_that_has_no_photo_is_not_worth_a_render(self):
        assert repair(context(photo=""), verdict(readable=False), tried=set()) is None

    def test_dropping_a_body_that_is_already_empty_is_not_worth_a_render(self):
        assert repair(context(body=""), verdict(issues=["tartib"]), tried=set()) is None

    def test_shrinking_stops_at_a_floor(self):
        """Below this the headline is smaller than the body and looks broken."""
        from app.services.visual_repair import MIN_TITLE_SIZE

        small = context(layout={"title_size": MIN_TITLE_SIZE, "body_size": 36, "padding": 80})
        fixed = repair(small, verdict(complete=False), tried=set())

        # Nothing left to shrink, so it escalates to the next clipping repair.
        assert fixed is None or len(fixed["title"]) < len(small["title"])
