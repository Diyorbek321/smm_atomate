"""Floating cards — the layout that makes a frame read as designed.

The reference clips build their compositions out of two or three rounded cards
that overlap and arrive one after another. Every scene this engine produced was
a single centred column, which is why they read as slides no matter how well
the type was set.

`makePane` has always taken arbitrary geometry; only the layout branch was
hard-coded to a half-and-half split. Cards are that same machinery with the
geometry read from the archetype, which is why this is a small change rather
than a second renderer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.promo_brief import _FIELDS
from app.services.promo_families import Brand
from app.services.promo_scenes import _archetype, archetype_names, build_script

BRAND = Brand.from_colors(
    {"bg": "#0F2B63", "ink": "#FFFFFF", "accent": "#FFCE1B", "muted": "#7FB0FF"},
    mark="Postchi", cta="@inovatex",
)
TEMPLATE = Path("app/assets/promo/template.html").read_text(encoding="utf-8")
#: One test in this file drives a real browser; the rest are pure.
COPY = {"leftTitle": "Ko'rildi", "leftBody": "8 400 marta",
        "rightTitle": "Mijoz keldi", "rightBody": "14 ta"}


def script(timing=None):
    job = {"name": "k", "mood": "tezkor", "bpm": 118,
           "scenes": [{"use": "kartochka", "slot": "s0", "say": 0}],
           "say": ["Ikkalasi ham reklama, lekin biri pul keltiradi."],
           "text": {"s0": COPY}}
    return build_script(job, BRAND, timing=timing)


class TestTheArchetypeShips:
    def test_it_is_in_the_catalogue(self):
        assert "kartochka" in archetype_names()

    def test_the_model_can_fill_it(self):
        needs = {n.rstrip("[]?") for n in _archetype("kartochka")["needs"]}
        assert needs <= set(_FIELDS["kartochka"].values())

    def test_it_asks_for_a_cards_layout(self):
        assert _archetype("kartochka")["layout"] == "cards"


class TestTheGeometryIsAuthored:
    def test_every_card_carries_its_own_place(self):
        for card in _archetype("kartochka")["cards"]:
            assert {"x", "y", "w", "h"} <= set(card), card.get("bg")

    def test_the_cards_overlap(self):
        """Cards in a neat row are a table. The overlap is the composition."""
        cards = _archetype("kartochka")["cards"]
        a, b = cards[0], cards[1]
        assert a["x"] + a["w"] > b["x"]

    def test_they_stay_inside_the_frame(self):
        for card in _archetype("kartochka")["cards"]:
            assert card["x"] >= 0 and card["y"] >= 0
            assert card["x"] + card["w"] <= 1080
            assert card["y"] + card["h"] <= 1920

    def test_each_card_is_rounded_and_lifted(self):
        for card in _archetype("kartochka")["cards"]:
            assert card.get("radius"), "kartochka burchaksiz — bu panel, kartochka emas"


class TestTheyArriveOneAtATime:
    def test_no_two_cards_land_together(self):
        """Three cards arriving at once is one composition appearing; arriving
        in sequence is an edit."""
        times = [card["at"] for card in _archetype("kartochka")["cards"]]
        assert times == sorted(times)
        assert len(set(times)) == len(times)

    def test_the_template_animates_a_card_that_asks_for_it(self):
        assert "if(c.at==null) return;" in TEMPLATE

    def test_a_pane_without_a_time_is_left_alone(self):
        """Split and full-bleed panes have no `at` and must not be touched, or
        every existing archetype starts at zero opacity."""
        assert "c.at==null" in TEMPLATE


class TestItComposes:
    def test_the_scene_builds_with_its_cards(self):
        scene = script()["scenes"][0]
        assert len(scene["cards"]) == 3
        assert scene["layout"] == "cards"

    def test_the_copy_reaches_the_right_cards(self):
        blob = json.dumps(script(), ensure_ascii=False)
        for value in COPY.values():
            assert value in blob

    def test_narration_reaches_a_card(self):
        """The karaoke fill walked `columns` and not `cards`, so the narration
        card rendered as an empty rectangle — which looks like a styling bug
        and was a missing branch in the composer."""
        timing = [{"src": "/a.wav", "dur": 3.4, "words": [
            {"w": "Ikkalasi", "at": 0.0, "b": False},
            {"w": "pul", "at": 2.2, "b": True}]}]
        scene = script(timing)["scenes"][0]
        karaoke = [line for card in scene["cards"] for line in card.get("lines", [])
                   if line.get("kind") == "karaoke"]
        assert karaoke, "kartochkada karaoke qatori yo'q"
        assert karaoke[0].get("words"), "karaoke so'zsiz qoldi"

    @pytest.mark.parametrize("archetype", ["taqqoslash", "matn", "stat"])
    def test_the_older_layouts_are_untouched(self, archetype):
        spec = _archetype(archetype)
        assert spec.get("layout") != "cards"
        assert "cards" not in spec


class TestTheCardsFitWhatGoesInThem:
    """A card sized for a short sentence and an agent that writes long ones.

    The first real clip to use this archetype came back with a QC warning —
    312px of narration in a 262px card. The template clips overflow rather than
    spilling it, so nothing looked broken; the last line was simply gone.
    """

    @staticmethod
    def _usable_width(card: dict) -> float:
        return card["w"] - 2 * card.get("pad", 90)

    def test_no_line_is_told_to_wrap_wider_than_its_card(self):
        """`wrap` measured against space the card does not have is a line that
        fits on paper and is cut on screen."""
        from app.services.promo_scenes import _archetype

        for card in _archetype("kartochka")["cards"]:
            for line in card["lines"]:
                if line.get("wrap"):
                    assert line["wrap"] <= self._usable_width(card), line

    async def test_a_long_narration_still_fits(self):
        """The agent writes to a word budget, not to this card's height."""
        from playwright.async_api import async_playwright

        from app.services.promo import TEMPLATE, _localise

        long_line = ("Reklamaga ketgan pul o'z-o'zidan mijoz keltirmaydi, "
                     "chunki e'lon ko'rilgani bilan hech kim yozmaydi.")
        job = {"name": "k", "mood": "tezkor", "bpm": 118,
               "scenes": [{"use": "kartochka", "slot": "s0", "say": 0}],
               "say": [long_line],
               "text": {"s0": {"leftTitle": "Ko'rildi", "leftBody": "8 400 marta ko'rsatildi",
                               "rightTitle": "Mijoz keldi", "rightBody": "14 ta odam yozdi"}}}
        timing = [{"src": "/a.wav", "dur": 5.0, "words": [
            {"w": w, "at": i * 0.32, "b": False} for i, w in enumerate(long_line.split())]}]
        script = _localise(build_script(job, BRAND, timing=timing))

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1080, "height": 1920})
            await page.goto(TEMPLATE.as_uri(), wait_until="networkidle")
            await page.evaluate("() => document.fonts.ready")
            await page.evaluate("s => window.build(s)", script)
            await page.evaluate("() => document.fonts.ready")
            await page.evaluate("() => window.fit()")
            issues = await page.evaluate("() => window.measure()")
            await browser.close()
        assert not issues, issues

    def test_every_card_stays_on_screen(self):
        from app.services.promo_scenes import _archetype

        for card in _archetype("kartochka")["cards"]:
            assert card["y"] + card["h"] <= 1920, card
