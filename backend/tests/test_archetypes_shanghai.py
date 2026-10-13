"""Two moves lifted out of a clip a person made by hand.

`promo/out/shanghai-ielts-promo.mp4` was written scene by scene in August,
before any of this existed, and it still reads better than most of what the
engine produces. Two of its moves were the reason, and the template could
already draw both — nothing had ever asked it to:

* **Naming the wrong answer and crossing it out.** "Muammo — GRAMMATIKA",
  struck through, then "emas." A rhetorical move none of the thirteen
  archetypes could make, and the one that carries the whole argument.
* **The lettered formula.** A/R/E, each letter glowing, each row arriving on
  its own beat. `kind: row` has drawn this since the beginning; only `royxat`
  used it, and only for numbered items.

Turning a hand-made clip into archetypes is the cheapest motion design
available: the judgement was already spent, and this makes it repeatable.
"""

from __future__ import annotations

import pytest

from app.agents.promo_brief import _FIELDS, SceneCopy, _beat, _copy_for
from app.services.promo_families import Brand
from app.services.promo_scenes import _archetype, archetype_names, build_script

BRAND = Brand.from_colors(
    {"bg": "#0B1416", "ink": "#F2F6F8", "accent": "#2FD9C4", "muted": "#63727E"},
    mark="Shanghai", cta="Birinchi dars — bepul",
)


def script_for(use: str, text: dict) -> dict:
    job = {"name": "sh", "mood": "qorongu", "bpm": 112,
           "scenes": [{"use": use, "slot": "s0", "dur": 5.0}],
           "say": [], "text": {"s0": text}}
    return build_script(job, BRAND)


class TestBothShip:
    def test_they_are_in_the_catalogue(self):
        assert {"tuzatish", "formula"} <= set(archetype_names())

    def test_the_model_can_fill_them(self):
        """An archetype the copy schema cannot reach is one nothing can pick."""
        for name in ("tuzatish", "formula"):
            assert name in _FIELDS, name
            needs = {n.rstrip("[]?") for n in _archetype(name)["needs"]}
            reachable = set(_FIELDS[name].values())
            assert needs <= reachable, (name, needs - reachable)


class TestCrossingOutTheWrongAnswer:
    def test_the_wrong_answer_is_struck_through(self):
        script = script_for("tuzatish", {"setup": "Muammo —", "wrong": "GRAMMATIKA"})
        lines = script["scenes"][0]["lines"]
        struck = [line for line in lines if line.get("strike")]
        assert len(struck) == 1
        assert struck[0]["text"] == "GRAMMATIKA"

    def test_the_verdict_lands_after_the_strike_not_before(self):
        """Reading "emas." before the line is crossed out is the joke told
        backwards — the strike has to complete first."""
        lines = script_for("tuzatish",
                           {"setup": "Muammo —", "wrong": "GRAMMATIKA"})["scenes"][0]["lines"]
        struck = next(line for line in lines if line.get("strike"))
        verdict = lines[-1]
        assert verdict["at"] > struck["at"] + struck["strikeAt"]

    def test_the_verdict_has_a_default_worth_having(self):
        """It is "emas." nine times in ten; asking for it every time is a
        field that can only be got wrong."""
        lines = script_for("tuzatish",
                           {"setup": "Muammo —", "wrong": "GRAMMATIKA"})["scenes"][0]["lines"]
        assert lines[-1]["text"] == "emas."

    def test_the_verdict_can_still_be_overridden(self):
        lines = script_for("tuzatish", {"setup": "Sabab —", "wrong": "PUL",
                                        "verdict": "ham emas."})["scenes"][0]["lines"]
        assert lines[-1]["text"] == "ham emas."

    def test_the_setup_and_the_wrong_answer_are_typeset_differently(self):
        """The soft half is serif italic, the hard half is the display face.
        Setting both the same throws away the contrast the move relies on."""
        lines = script_for("tuzatish",
                           {"setup": "Muammo —", "wrong": "GRAMMATIKA"})["scenes"][0]["lines"]
        assert lines[0]["kind"] == "serif"
        assert lines[1]["kind"] != "serif"

    def test_the_model_supplies_only_the_two_halves_it_should(self):
        assert _copy_for("tuzatish", SceneCopy(caption="Muammo —", title="GRAMMATIKA")) == {
            "setup": "Muammo —", "wrong": "GRAMMATIKA"}


class TestTheLetteredFormula:
    def test_the_letter_comes_from_the_word(self):
        """Asking for it separately buys a field that can disagree with the
        word beside it."""
        assert _beat("ANSWER: to'g'ridan-to'g'ri javob") == {
            "letter": "A", "word": "ANSWER", "desc": "to'g'ridan-to'g'ri javob"}

    def test_a_row_with_no_description_still_works(self):
        assert _beat("ANSWER") == {"letter": "A", "word": "ANSWER", "desc": ""}

    @pytest.mark.parametrize("line", ["  answer : javob ", "answer:javob"])
    def test_spacing_and_case_do_not_matter(self, line):
        beat = _beat(line)
        assert beat["letter"] == "A" and beat["word"].lower() == "answer"

    def test_the_rows_arrive_one_at_a_time(self):
        """All three landing together is a bullet list, not a formula."""
        script = script_for("formula", {"title": "FORMULA", "items": [
            {"letter": "A", "word": "ANSWER", "desc": "javob"},
            {"letter": "R", "word": "REASON", "desc": "sabab"},
            {"letter": "E", "word": "EXAMPLE", "desc": "misol"}]})
        rows = [line for line in script["scenes"][0]["lines"] if line.get("kind") == "row"]
        assert len(rows) == 3
        times = [row["at"] for row in rows]
        assert times == sorted(times) and len(set(times)) == 3

    def test_each_row_carries_its_letter_word_and_note(self):
        script = script_for("formula", {"title": "FORMULA", "items": [
            {"letter": "A", "word": "ANSWER", "desc": "javob"}]})
        row = next(line for line in script["scenes"][0]["lines"] if line.get("kind") == "row")
        assert (row["letter"], row["word"], row["desc"]) == ("A", "ANSWER", "javob")

    def test_the_copy_schema_turns_plain_strings_into_rows(self):
        out = _copy_for("formula", SceneCopy(title="FORMULA", items=[
            "ANSWER: javob", "REASON: sabab"]))
        assert [item["letter"] for item in out["items"]] == ["A", "R"]
