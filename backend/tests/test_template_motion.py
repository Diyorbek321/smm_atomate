"""Does the template actually animate — asked of rendered frames, not of JSON.

The card layout introduced a per-pane time offset and read it off `p.spec.at`.
For a card that is a number. For every other pane `p.spec` *is* the scene spec,
whose `at` is the `[start, end]` pair — and `0 + [0,4] + 0.24` is a string in
JavaScript, so every line in every archetype silently stopped animating.

The whole suite stayed green, because nothing in it drove the template. These
tests do: they build a scene, set a time, and read what the browser computed.
That is the only kind of test that could have failed.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.services.promo import TEMPLATE, _localise
from app.services.promo_families import Brand
from app.services.promo_scenes import build_script

pytestmark = pytest.mark.chromium

BRAND = Brand.from_colors(
    {"bg": "#0F2B63", "ink": "#FFFFFF", "accent": "#FFCE1B", "muted": "#9FB8E8"},
    mark="Sinov", cta="@sinov",
)


async def nodes_at(use: str, text: dict, when: float, *, ref: dict | None = None):
    """What the browser computed for one scene's lines at a moment."""
    from playwright.async_api import async_playwright

    job = {"name": "t", "mood": "tezkor", "bpm": 118,
           "scenes": [{"use": use, "slot": "s0", "dur": 5.0, **(ref or {})}],
           "say": [], "text": {"s0": text}}
    script = _localise(build_script(job, BRAND))
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1080, "height": 1920})
        await page.goto(TEMPLATE.as_uri(), wait_until="networkidle")
        await page.evaluate("s => window.build(s)", script)
        await page.evaluate("() => window.fit()")
        await page.evaluate("t => window.setTime(t)", when)
        out = await page.evaluate("""() => EL.scenes[0].panes.flatMap(p =>
            p.nodes.map(o => ({
              kind: o.kind,
              opacity: parseFloat(o.node.style.opacity || '1'),
              line: o.line ? o.line.style.transform : null,
              chars: o.chars ? o.chars.map(c => parseFloat(c.style.opacity || '0')) : null,
            })))""")
        await browser.close()
    return out


class TestEveryArchetypeStillAnimates:
    """The regression the card layout caused, asked directly."""

    @pytest.mark.parametrize("use,text", [
        ("matn", {}),
        ("stat", {"label": "Xato", "to": 70}),
        ("cta", {"headline": "Yozing"}),
        ("royxat", {"title": "T", "items": ["bir", "ikki"]}),
    ])
    async def test_lines_are_visible_once_their_time_has_come(self, use, text):
        for node in await nodes_at(use, text, 2.5):
            assert node["opacity"] > 0.5, (use, node["kind"], node["opacity"])

    async def test_nothing_is_visible_before_the_scene_starts(self):
        """The mirror of the above: opacity 1 everywhere would pass the test
        above while meaning the animation is simply not running."""
        nodes = await nodes_at("stat", {"label": "Xato", "to": 70}, 0.0)
        assert any(node["opacity"] < 0.5 for node in nodes)


class TestTheCalloutDraws:
    COPY: ClassVar[dict] = {"a_text": "Suv", "a_sub": "100m", "b_text": "Po'lat", "c_text": "Kafolat"}

    async def test_the_line_reaches_full_length(self):
        nodes = await nodes_at("belgilar", self.COPY, 2.5)
        lines = [n["line"] for n in nodes if n["kind"] == "callout"]
        assert lines and all("scaleX(1)" in line for line in lines), lines

    async def test_it_has_not_drawn_yet_at_the_start(self):
        """A callout that is already drawn is a label, not a pointer."""
        nodes = await nodes_at("belgilar", self.COPY, 0.05)
        lines = [n["line"] for n in nodes if n["kind"] == "callout"]
        assert lines and all("scaleX(0)" in line for line in lines)

    async def test_the_callouts_draw_one_after_another(self):
        """Their `at` values are 0.24 / 0.66 / 1.08 and each draw takes ~0.44s,
        so just before a second the first is finished and the last has not
        begun. Three lines drawing together would be one diagram appearing."""
        nodes = await nodes_at("belgilar", self.COPY, 0.95)
        drawn = [n["line"] for n in nodes if n["kind"] == "callout"]
        assert any("scaleX(1)" in line for line in drawn), drawn
        assert any("scaleX(0)" in line for line in drawn), drawn


class TestTheTypewriter:
    async def test_characters_arrive_in_order(self):
        nodes = await nodes_at(
            "matn", {}, 0.4,
            ref={"lines": [{"kind": "display", "text": "SALOM DUNYO", "type": True,
                            "size": 70, "at": 0.0, "dur": 0.3, "out": 99}]})
        chars = next(n["chars"] for n in nodes if n["chars"])
        assert chars[0] > chars[-1], "harflar tartib bilan chiqmayapti"

    async def test_every_character_is_there_by_the_end(self):
        nodes = await nodes_at(
            "matn", {}, 2.5,
            ref={"lines": [{"kind": "display", "text": "SALOM DUNYO", "type": True,
                            "size": 70, "at": 0.0, "dur": 0.3, "out": 99}]})
        chars = next(n["chars"] for n in nodes if n["chars"])
        assert len(chars) == len("SALOM DUNYO")
        assert all(value > 0.9 for value in chars)

    async def test_a_line_without_the_flag_is_not_split(self):
        """Splitting every line into spans would change how they measure."""
        nodes = await nodes_at("cta", {"headline": "Yozing"}, 2.5)
        assert all(node["chars"] is None for node in nodes)
