"""VideoPromptAgent's deterministic half.

The model only writes the creative part — concept, scenes, sound. Everything a
HyperFrames run needs to succeed (install line, canvas size, brand accent,
facts to stay inside, render-to-MP4) is assembled here, so that is what these
tests pin down. The LLM call itself is covered by the fallback path.
"""

from __future__ import annotations

import pytest

from app.agents.video_prompt import (
    ASPECTS,
    FORMATS,
    VideoConcept,
    VideoPromptAgent,
    VideoPromptRequest,
    clamp_duration,
    clean_scenes,
    compose_prompt,
    fallback_concept,
    unknown_numbers,
)
from tests.test_agents import make_business, make_knowledge


def request(**overrides) -> VideoPromptRequest:
    values = {
        "business": make_business(),
        "knowledge": make_knowledge(brand_colors={"accent": "#FF5B2E", "bg": "#101010"}),
        "goal": "Sentabr IELTS guruhiga yozilish",
        "format": "promo",
        "duration": 15,
        "aspect": "9:16",
    }
    values.update(overrides)
    return VideoPromptRequest(**values)


def concept(**overrides) -> VideoConcept:
    values = {
        "title": "Band joy",
        "concept": "Kalendar varaqlari yiqilib, bitta sana urg'u rangida qoladi.",
        "message": "Sentabr guruhida joy oz qoldi",
        "scenes": ["0–3s: kalendar varaqlanadi", "3–8s: 8.0 IELTS o'qituvchisi", "8–15s: lockup va CTA"],
        "sound": "Varaq shitirlashi, har beat'da tick, oxirida zarb.",
        "closing": "@brightacademy ga yozing",
    }
    values.update(overrides)
    return VideoConcept(**values)


class TestClampDuration:
    @pytest.mark.parametrize(("given", "expected"), [(15, 15), (1, 6), (0, 6), (300, 60), (-5, 6)])
    def test_bounds(self, given: int, expected: int):
        assert clamp_duration(given) == expected


class TestCleanScenes:
    def test_drops_blank_and_trims(self):
        assert clean_scenes(["  bir  ", "", "   ", "ikki"]) == ["bir", "ikki"]

    def test_caps_count(self):
        assert len(clean_scenes([f"sahna {i}" for i in range(20)])) == 8

    def test_truncates_long_scene(self):
        assert len(clean_scenes(["x" * 1000])[0]) <= 400

    def test_cuts_on_a_word_boundary(self):
        scene = clean_scenes(["so'z " * 200])[0]
        assert scene.endswith("…")
        assert not scene[:-1].endswith("so'")


class TestUnknownNumbers:
    def test_flags_invented_price(self):
        c = concept(scenes=["0–3s: Narxi 800 000 so'm", "3–6s: x", "6–15s: y"])
        assert unknown_numbers(c, "IELTS intensiv 600000 UZS") == ["800000"]

    def test_known_numbers_pass_even_when_formatted(self):
        c = concept(scenes=["0–3s: atigi 600 000 so'm", "3–6s: 8.0 ball", "6–15s: y"])
        assert unknown_numbers(c, "600000 UZS, 8.0 IELTS o'qituvchisi") == []

    def test_time_ranges_are_not_facts(self):
        c = concept(scenes=["0–3s: a", "3-8s: b", "8–15s: c"], message="", closing="", sound="12s da zarb")
        assert unknown_numbers(c, "") == []


class TestComposePrompt:
    def test_carries_every_technical_requirement(self):
        text = compose_prompt(request(), concept())
        assert "npx hyperframes skills update" in text
        assert "/hyperframes" in text
        assert "Node.js" in text and "FFmpeg" in text
        assert "1080x1920" in text
        assert "15 soniyalik" in text
        assert "MP4" in text
        assert "kod orqali" in text

    def test_uses_brand_accent_not_default(self):
        text = compose_prompt(request(), concept())
        assert "#FF5B2E" in text

    def test_canvas_follows_aspect(self):
        for aspect, (w, h) in ASPECTS.items():
            assert f"{w}x{h}" in compose_prompt(request(aspect=aspect), concept())

    def test_names_the_business_and_its_facts(self):
        text = compose_prompt(request(), concept())
        assert "Bright Academy" in text
        assert "8.0 IELTS o'qituvchisi" in text
        assert "@brightacademy" in text

    def test_numbers_scenes_in_order(self):
        text = compose_prompt(request(), concept())
        first = text.index("1. 0–3s")
        third = text.index("3. 8–15s")
        assert first < third

    def test_banned_words_are_forwarded(self):
        kb = make_knowledge(brand_kit={"voice": {"banned_words": ["arzon"]}})
        assert "arzon" in compose_prompt(request(knowledge=kb), concept())

    def test_relative_logo_becomes_absolute(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "public_base_url", "https://api.example.uz/")
        kb = make_knowledge(logo_url="/media/brand/logo.png")
        assert "https://api.example.uz/media/brand/logo.png" in compose_prompt(request(knowledge=kb), concept())

    def test_survives_missing_knowledge(self):
        text = compose_prompt(request(knowledge=None), concept())
        assert "Bright Academy" in text
        assert "MP4" in text

    def test_empty_concept_fields_leave_no_blank_labels(self):
        text = compose_prompt(request(), concept(sound="", closing=""))
        assert "Tovush:\n" not in text
        assert "Yakun: \n" not in text


class TestFallback:
    def test_fallback_concept_is_usable(self):
        result = fallback_concept(request())
        assert result.concept
        assert len(result.scenes) >= 3

    @pytest.mark.asyncio
    async def test_agent_falls_back_when_model_fails(self, monkeypatch):
        agent = VideoPromptAgent()

        async def boom(*args, **kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr(agent, "ask_json", boom)
        result = await agent.run(request())
        assert result.fallback is True
        assert "npx hyperframes skills update" in result.prompt

    @pytest.mark.asyncio
    async def test_agent_uses_model_concept(self, monkeypatch):
        agent = VideoPromptAgent()

        async def fake(*args, **kwargs):
            return concept()

        monkeypatch.setattr(agent, "ask_json", fake)
        result = await agent.run(request())
        assert result.fallback is False
        assert "Kalendar varaqlari" in result.prompt

    @pytest.mark.asyncio
    async def test_invented_number_triggers_one_rewrite(self, monkeypatch):
        agent = VideoPromptAgent()
        calls = []

        async def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return concept(message="Narxi 999 000 so'm")
            return concept()

        monkeypatch.setattr(agent, "ask_json", fake)
        result = await agent.run(request())
        assert len(calls) == 2
        assert "999000" in calls[1]
        assert "999" not in result.prompt
        assert result.unverified == []

    @pytest.mark.asyncio
    async def test_persisting_invented_number_is_reported(self, monkeypatch):
        agent = VideoPromptAgent()

        async def fake(*args, **kwargs):
            return concept(message="Narxi 999 000 so'm")

        monkeypatch.setattr(agent, "ask_json", fake)
        result = await agent.run(request())
        assert result.unverified == ["999000"]
        assert "999000" in result.prompt  # owner sees the warning inside the prompt

    @pytest.mark.asyncio
    async def test_too_few_scenes_falls_back(self, monkeypatch):
        agent = VideoPromptAgent()

        async def thin(*args, **kwargs):
            return concept(scenes=["faqat bitta"])

        monkeypatch.setattr(agent, "ask_json", thin)
        result = await agent.run(request())
        assert result.fallback is True


def test_formats_have_labels():
    assert {"showreel", "promo", "explainer", "elon", "natija"} <= set(FORMATS)
    assert all(label.strip() for label, _ in FORMATS.values())
