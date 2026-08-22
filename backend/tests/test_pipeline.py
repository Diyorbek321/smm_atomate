"""Full multi-agent pipeline with a stubbed Gemini backend.

No network calls: `GeminiClient.generate_structured` is replaced by a fake that
answers each schema with realistic content, so the wiring, the pillar
distribution, scheduling and image rendering are all exercised for real.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.business import Business
from app.models.enums import (
    PILLAR_DISTRIBUTION,
    BusinessCategory,
    ContentItemStatus,
    ContentPillar,
    ContentType,
    Language,
    ToneOfVoice,
)
from app.models.knowledge_base import KnowledgeBase
from app.utils.dates import utcnow

pytestmark = pytest.mark.db


@pytest.fixture
async def business(session) -> Business:
    business = Business(
        name="Bright IELTS",
        slug=f"bright-{utcnow().timestamp()}",
        category=BusinessCategory.EDUCATION,
        tone_of_voice=ToneOfVoice.CASUAL,
        target_audience="18-30 yosh",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={"posts_per_week": 8, "posting_hours": [9, 13, 18]},
    )
    session.add(business)
    await session.flush()

    knowledge = KnowledgeBase(
        business_id=business.id,
        key_offerings=[{"name": "IELTS intensiv", "duration": "3 oy"}],
        prices=[{"item": "IELTS intensiv", "price": 600000, "currency": "UZS"}],
        usps=["8.0 ballik o'qituvchi"],
        teacher_profiles=[{"name": "Aziz", "role": "IELTS"}],
        faq=[{"q": "Qachon?", "a": "18:00"}],
        success_stories=[{"name": "Dilnoza", "result": "7.5"}],
        raw_notes="Markaz 2019 yildan beri ishlaydi.",
        phone="+998901234567",
        telegram_username="brightielts",
        brand_colors={"accent": "#FF6B35"},
        banned_topics=[],
        preferred_hashtags=["#ielts"],
        competitors=[],
    )
    session.add(knowledge)
    await session.flush()
    business.knowledge_base = knowledge
    return business


@pytest.fixture(autouse=True)
def stub_gemini(monkeypatch):
    """Answer every structured request with schema-appropriate fake content."""
    from app.schemas.content import CopyOutputStrict, EditorOutput, StrategyOutput
    from app.schemas.knowledge_base import KnowledgeExtraction
    from app.services.gemini import GeminiResult

    calls: list[str] = []

    async def fake_structured(self, prompt, schema, **kwargs):
        calls.append(schema.__name__)
        result = GeminiResult(text="{}", model="fake", prompt_tokens=100, output_tokens=200)

        if schema is StrategyOutput:
            # Deliberately return NO slots: the strategist must fall back to
            # its deterministic blueprint and still honour the distribution.
            return StrategyOutput(theme="Avgust intensivi", objectives=["Ariza"], slots=[]), result

        if schema is CopyOutputStrict:
            return (
                CopyOutputStrict(
                    headline="IELTS 7.0 uch oyda",
                    hook="Ko'pchilik listeningda yiqiladi.",
                    caption_tg="IELTS 7.0 olish uchun kuniga 30 daqiqa listening qiling. "
                    "Guruhda 4 ta joy qoldi.",
                    caption_ig="IELTS 7.0 olish uchun kuniga 30 daqiqa listening qiling.",
                    cta="Bepul darsga yozilish uchun +998901234567 ga qo'ng'iroq qiling",
                    hashtags=["ielts", "toshkent"],
                    slides=[
                        {"title": f"Slayd {i}", "body": "Qisqa matn bu yerda turadi."} for i in range(1, 6)
                    ],
                    quiz={
                        "question": "IELTS maksimal bali nechchi?",
                        "answers": ["9.0", "10.0", "8.0"],
                        "correct_option_id": 0,
                        "explanation": "IELTS 9.0 gacha baholanadi.",
                    },
                    script={
                        "duration_sec": 30,
                        "voiceover": "IELTS haqida",
                        "scenes": [{"t": "0-3s", "shot": "hook", "on_screen": "IELTS 7.0", "voice": "..."}],
                    },
                ),
                result,
            )

        if schema is EditorOutput:
            return EditorOutput(approved=True, score=9.0, issues=[], summary="Yaxshi"), result

        if schema is KnowledgeExtraction:
            return KnowledgeExtraction(summary="ok", next_question=None), result

        # VisualBrief and anything else: build an empty instance.
        return schema(), result

    monkeypatch.setattr(
        "app.services.gemini.GeminiClient.generate_structured", fake_structured, raising=True
    )
    monkeypatch.setattr("app.core.config.settings.gemini_api_key", "test-key", raising=False)
    return calls


class TestPlanGeneration:
    async def test_plan_creates_items_with_exact_pillar_distribution(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        result = await ContentPipeline(session).generate_plan(
            business.id, starts_on=date(2026, 8, 17), horizon_days=7, posts_count=8
        )

        assert result.plan is not None
        assert len(result.items) == 8
        assert not result.failures

        counts: dict[ContentPillar, int] = {}
        for item in result.items:
            counts[item.pillar] = counts.get(item.pillar, 0) + 1

        assert sum(counts.values()) == 8
        for pillar, share in PILLAR_DISTRIBUTION.items():
            assert abs(counts.get(pillar, 0) - share * 8) <= 1

    async def test_items_are_scheduled_within_the_horizon(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        result = await ContentPipeline(session).generate_plan(
            business.id, starts_on=date(2026, 8, 17), horizon_days=7, posts_count=6
        )
        days = {item.scheduled_at.date() for item in result.items}
        assert min(days) >= date(2026, 8, 16)      # UTC shift can move it a day earlier
        assert max(days) <= date(2026, 8, 24)

    async def test_items_await_human_review(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        result = await ContentPipeline(session).generate_plan(
            business.id, starts_on=date(2026, 8, 17), posts_count=4
        )
        assert all(item.status == ContentItemStatus.PENDING_REVIEW for item in result.items)

    async def test_auto_approve_setting_is_respected(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        business.settings = {**business.settings, "auto_approve": True}
        await session.flush()

        result = await ContentPipeline(session).generate_plan(
            business.id, starts_on=date(2026, 8, 17), posts_count=4
        )
        assert all(item.status == ContentItemStatus.APPROVED for item in result.items)

    async def test_captions_carry_cta_and_contacts(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        result = await ContentPipeline(session).generate_plan(
            business.id, starts_on=date(2026, 8, 17), posts_count=4
        )
        for item in result.items:
            assert "+998901234567" in item.caption_tg
            assert item.cta
            assert item.hashtags

    async def test_quality_score_recorded(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        result = await ContentPipeline(session).generate_plan(
            business.id, starts_on=date(2026, 8, 17), posts_count=4
        )
        assert all(item.quality_score > 0 for item in result.items)
        assert all("issues" in (item.editor_report or {}) for item in result.items)

    async def test_regenerating_the_same_week_reuses_the_plan(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        first = await ContentPipeline(session).generate_plan(
            business.id, starts_on=date(2026, 8, 17), posts_count=4
        )
        second = await ContentPipeline(session).generate_plan(
            business.id, starts_on=date(2026, 8, 17), posts_count=4
        )
        assert first.plan is not None and second.plan is not None
        assert first.plan.id == second.plan.id

    async def test_usage_is_tracked(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        result = await ContentPipeline(session).generate_plan(
            business.id, starts_on=date(2026, 8, 17), posts_count=4
        )
        assert result.usage.calls > 0
        assert result.usage.prompt_tokens > 0


class TestSingleItem:
    async def test_quiz_item_is_telegram_only(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        item = await ContentPipeline(session).generate_single(
            business.id,
            content_type=ContentType.TELEGRAM_QUIZ,
            pillar=ContentPillar.INTERACTIVE,
            topic="IELTS quiz",
        )
        assert item.needs_telegram
        assert not item.needs_instagram
        assert item.options["answers"]
        assert item.options["correct_option_id"] == 0

    async def test_carousel_renders_slide_images(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        item = await ContentPipeline(session).generate_single(
            business.id,
            content_type=ContentType.CAROUSEL,
            pillar=ContentPillar.EDUCATIONAL,
            topic="5 ta xato",
            render_image=True,
        )
        assert len(item.carousel_slides) == 5
        # Rendering falls back to Pillow when Chromium is unavailable, but a
        # real PNG must exist either way.
        assert all(slide.get("image_url") for slide in item.carousel_slides)
        assert item.image_url == item.carousel_slides[0]["image_url"]

    async def test_regenerate_bumps_counter_and_resets_review(self, session, business, stub_gemini):
        from app.agents.orchestrator import ContentPipeline

        pipeline = ContentPipeline(session)
        item = await pipeline.generate_single(business.id, topic="Boshlang'ich post")
        item.status = ContentItemStatus.APPROVED
        item.sent_for_review = True
        await session.flush()

        await pipeline.regenerate(item, instruction="Narxni 400 ming qil")

        assert item.regeneration_count == 1
        assert item.status == ContentItemStatus.PENDING_REVIEW
        assert item.sent_for_review is False


class TestRenderedMedia:
    async def test_story_card_is_a_real_png(self, session, business, stub_gemini):
        from pathlib import Path

        from app.agents.orchestrator import ContentPipeline
        from app.core.config import settings

        item = await ContentPipeline(session).generate_single(
            business.id, content_type=ContentType.STORY, pillar=ContentPillar.SALES, topic="Chegirma"
        )
        assert item.image_url

        relative = item.image_url.split(settings.media_url_prefix + "/")[-1]
        path = Path(settings.media_root) / relative
        assert path.exists()
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
