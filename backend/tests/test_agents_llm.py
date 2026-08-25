"""Onboarding and feedback agents against a stubbed Gemini backend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.business import Business
from app.models.content_item import ContentItem
from app.models.enums import (
    BusinessCategory,
    ContentItemStatus,
    ContentPillar,
    ContentType,
    Language,
    Platform,
    ToneOfVoice,
)
from app.models.knowledge_base import KnowledgeBase
from app.schemas.content import VoiceInstruction
from app.schemas.knowledge_base import KnowledgeExtraction, Offering, PriceItem
from app.services.gemini import GeminiResult


def make_business() -> Business:
    return Business(
        name="Bright IELTS",
        category=BusinessCategory.EDUCATION,
        tone_of_voice=ToneOfVoice.CASUAL,
        target_audience="",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={},
    )


def empty_knowledge() -> KnowledgeBase:
    return KnowledgeBase(
        key_offerings=[], prices=[], usps=[], teacher_profiles=[], faq=[], success_stories=[],
        raw_notes="", banned_topics=[], preferred_hashtags=[], competitors=[], brand_colors={},
        version=1, completeness_score=0.0,
    )


@pytest.fixture
def stub_gemini(monkeypatch):
    """Return a canned object per requested schema; records the prompts."""
    prompts: list[str] = []
    answers: dict[str, object] = {}

    async def fake_structured(self, prompt, schema, **kwargs):
        prompts.append(prompt)
        result = GeminiResult(text="{}", model="fake", prompt_tokens=10, output_tokens=20)
        answer = answers.get(schema.__name__)
        if answer is None:
            raise AssertionError(f"no canned answer for {schema.__name__}")
        return answer, result

    monkeypatch.setattr("app.services.gemini.GeminiClient.generate_structured", fake_structured)
    monkeypatch.setattr("app.core.config.settings.gemini_api_key", "test-key", raising=False)
    return {"prompts": prompts, "answers": answers}


class TestOnboardingIngest:
    async def test_extraction_is_merged_and_scored(self, stub_gemini):
        from app.agents.onboarding import OnboardingAgent

        stub_gemini["answers"]["KnowledgeExtraction"] = KnowledgeExtraction(
            key_offerings=[Offering(name="IELTS intensiv", duration="3 oy")],
            prices=[PriceItem(item="IELTS intensiv", price=600000)],
            usps=["8.0 ballik o'qituvchi"],
            phone="+998901234567",
            next_question="FAQ bormi?",
            summary="Kurs va narx saqlandi",
        )

        business, knowledge = make_business(), empty_knowledge()
        result = await OnboardingAgent().ingest(business, knowledge, "IELTS 600 ming, 3 oy")

        assert "key_offerings" in result.updated_fields
        assert "prices" in result.updated_fields
        assert knowledge.prices[0]["price"] == 600000
        assert knowledge.phone == "+998901234567"
        assert result.next_question == "FAQ bormi?"
        assert 0 < result.completeness < 1
        assert knowledge.version == 2

    async def test_prompt_carries_the_existing_profile(self, stub_gemini):
        from app.agents.onboarding import OnboardingAgent

        stub_gemini["answers"]["KnowledgeExtraction"] = KnowledgeExtraction(summary="ok")
        knowledge = empty_knowledge()
        knowledge.phone = "+998900000000"

        await OnboardingAgent().ingest(make_business(), knowledge, "yangi ma'lumot")

        prompt = stub_gemini["prompts"][0]
        assert "+998900000000" in prompt          # existing facts are shown
        assert "YETISHMAYOTGAN MAYDONLAR" in prompt
        assert "yangi ma'lumot" in prompt

    async def test_empty_message_short_circuits(self, stub_gemini):
        from app.agents.onboarding import OnboardingAgent

        result = await OnboardingAgent().ingest(make_business(), empty_knowledge(), "   ")
        assert result.updated_fields == []
        assert result.next_question is not None
        assert stub_gemini["prompts"] == []       # no tokens spent

    async def test_complete_profile_ends_the_interview(self, stub_gemini):
        from app.agents.onboarding import OnboardingAgent

        stub_gemini["answers"]["KnowledgeExtraction"] = KnowledgeExtraction(
            next_question="yana savol?", summary="ok"
        )
        knowledge = empty_knowledge()
        knowledge.key_offerings = [{"name": "IELTS"}]
        knowledge.prices = [{"item": "IELTS", "price": 1}]
        knowledge.usps = ["x"]
        knowledge.faq = [{"q": "a", "a": "b"}]
        knowledge.teacher_profiles = [{"name": "Aziz"}]
        knowledge.phone = "+998901234567"
        knowledge.raw_notes = "y" * 60

        result = await OnboardingAgent().ingest(make_business(), knowledge, "qo'shimcha")
        assert result.completeness == 1.0
        assert result.next_question is None      # nothing left to ask

    async def test_target_audience_is_backfilled(self, stub_gemini):
        from app.agents.onboarding import OnboardingAgent

        stub_gemini["answers"]["KnowledgeExtraction"] = KnowledgeExtraction(
            target_audience="18-30 yosh talabalar", summary="ok"
        )
        business = make_business()
        result = await OnboardingAgent().ingest(business, empty_knowledge(), "auditoriyamiz yoshlar")

        assert business.target_audience == "18-30 yosh talabalar"
        assert "target_audience" in result.updated_fields


@pytest.fixture
def stub_gemini_document(monkeypatch):
    """Canned answers for the document-understanding path; records the calls."""
    calls: list[dict] = []
    answers: dict[str, object] = {}

    async def fake_document(self, prompt, schema, *, data, mime_type, **kwargs):
        calls.append({"prompt": prompt, "mime_type": mime_type, "size": len(data)})
        result = GeminiResult(text="{}", model="fake", prompt_tokens=10, output_tokens=20)
        answer = answers.get(schema.__name__)
        if answer is None:
            raise AssertionError(f"no canned answer for {schema.__name__}")
        return answer, result

    monkeypatch.setattr(
        "app.services.gemini.GeminiClient.generate_structured_document", fake_document
    )
    monkeypatch.setattr("app.core.config.settings.gemini_api_key", "test-key", raising=False)
    return {"calls": calls, "answers": answers}


class TestOnboardingIngestDocument:
    async def test_pdf_extraction_is_merged(self, stub_gemini_document):
        from app.agents.onboarding import OnboardingAgent

        stub_gemini_document["answers"]["KnowledgeExtraction"] = KnowledgeExtraction(
            key_offerings=[Offering(name="IELTS intensiv", duration="3 oy")],
            prices=[PriceItem(item="IELTS intensiv", price=600000)],
            summary="Narxlar PDFdan olindi",
        )

        business, knowledge = make_business(), empty_knowledge()
        result = await OnboardingAgent().ingest_document(
            business, knowledge, b"%PDF-1.4 fake", filename="narxlar.pdf"
        )

        assert "key_offerings" in result.updated_fields
        assert knowledge.prices[0]["price"] == 600000
        assert "narxlar.pdf" in knowledge.raw_notes  # provenance survives
        call = stub_gemini_document["calls"][0]
        assert call["mime_type"] == "application/pdf"
        assert "narxlar.pdf" in call["prompt"]
        assert "MAVJUD BILIM BAZASI" in call["prompt"]

    async def test_empty_document_is_rejected(self, stub_gemini_document):
        from app.agents.onboarding import OnboardingAgent
        from app.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            await OnboardingAgent().ingest_document(make_business(), empty_knowledge(), b"")
        assert stub_gemini_document["calls"] == []  # no tokens spent

    async def test_oversized_document_is_rejected(self, stub_gemini_document, monkeypatch):
        from app.agents import onboarding
        from app.core.exceptions import ValidationError

        monkeypatch.setattr(onboarding, "MAX_DOCUMENT_BYTES", 10)
        with pytest.raises(ValidationError):
            await onboarding.OnboardingAgent().ingest_document(
                make_business(), empty_knowledge(), b"x" * 11
            )
        assert stub_gemini_document["calls"] == []


class TestFeedbackParse:
    def _item(self) -> ContentItem:
        return ContentItem(
            business_id=None,
            content_type=ContentType.FEED_POST,
            pillar=ContentPillar.SALES,
            platform=Platform.TELEGRAM,
            topic="IELTS",
            headline="Sarlavha",
            hook="",
            cta="",
            caption_tg="Narxi 600 ming so'm",
            caption_ig="",
            hashtags=[],
            carousel_slides=[],
            options={},
            script={},
            editor_report={},
            ai_meta={},
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            status=ContentItemStatus.PENDING_REVIEW,
            retry_count=0,
            regeneration_count=0,
            quality_score=0.0,
        )

    async def test_price_change_is_parsed(self, stub_gemini):
        from app.agents.feedback import FeedbackAgent

        stub_gemini["answers"]["VoiceInstruction"] = VoiceInstruction(
            action="change_price",
            new_value="400000",
            instruction_for_writer="Narxni 400 ming so'mga o'zgartir",
            confidence=0.95,
        )

        parsed = await FeedbackAgent().parse("Dushanbadagi narxni 400 ming qil", item=self._item())

        assert parsed.action == "change_price"
        assert parsed.new_value == "400000"
        prompt = stub_gemini["prompts"][0]
        assert "POST KONTEKSTI" in prompt
        assert "600 ming" in prompt               # the current copy is included

    async def test_empty_message_is_unknown(self, stub_gemini):
        from app.agents.feedback import FeedbackAgent

        parsed = await FeedbackAgent().parse("")
        assert parsed.action == "unknown"
        assert parsed.confidence == 0.0

    async def test_llm_failure_falls_back_to_keywords(self, monkeypatch):
        from app.agents.feedback import FeedbackAgent

        async def boom(self, prompt, schema, **kwargs):
            raise RuntimeError("gemini down")

        monkeypatch.setattr("app.services.gemini.GeminiClient.generate_structured", boom)
        monkeypatch.setattr("app.core.config.settings.gemini_api_key", "k", raising=False)

        parsed = await FeedbackAgent().parse("Bu postni bekor qil")
        assert parsed.action == "reject"
        assert parsed.confidence < 0.5


class TestEditorReflection:
    async def test_llm_findings_merge_with_local_rules(self, stub_gemini):
        from app.agents.editor import EditorAgent, EditorRequest
        from app.schemas.content import CopyOutput, EditorIssue, EditorOutput

        stub_gemini["answers"]["EditorOutput"] = EditorOutput(
            approved=True,
            score=9.0,
            issues=[EditorIssue(severity="minor", field="caption_tg", problem="Emoji ko'p")],
            fixed_caption_tg=(
                "Tuzatilgan matn bu yerda turadi va u yetarlicha uzun, telefon "
                "+998901234567 orqali bugunoq bog'laning, joylar cheklangan"
            ),
            summary="Kichik tuzatish",
        )

        knowledge = empty_knowledge()
        knowledge.phone = "+998901234567"
        copy = CopyOutput(
            caption_tg="Sentabr guruhida 12 joy qoldi, telefon +998901234567 shu yerda turadi albatta",
            caption_ig="Sentabr guruhida 12 joy qoldi, telefon +998901234567 shu yerda turadi albatta",
            cta="Qo'ng'iroq qiling",
            hashtags=["#ielts"],
        )

        result = await EditorAgent().run(
            EditorRequest(
                business=make_business(),
                knowledge=knowledge,
                copy=copy,
                content_type=ContentType.FEED_POST,
                topic="IELTS",
                deep_check=True,
            )
        )

        assert result.approved
        assert any(issue.problem == "Emoji ko'p" for issue in result.report.issues)
        assert result.copy.caption_tg.startswith("Tuzatilgan matn")

    async def test_critical_local_issue_overrides_a_happy_llm(self, stub_gemini):
        from app.agents.editor import EditorAgent, EditorRequest
        from app.schemas.content import CopyOutput, EditorOutput

        stub_gemini["answers"]["EditorOutput"] = EditorOutput(
            approved=True, score=10.0, issues=[], summary="Zo'r"
        )

        copy = CopyOutput(
            caption_tg="Narx [narx] so'm, telefon +998901234567 orqali bog'laning bugunoq albatta",
            caption_ig="Narx [narx] so'm, telefon +998901234567 orqali bog'laning bugunoq albatta",
            cta="Qo'ng'iroq qiling",
        )
        knowledge = empty_knowledge()
        knowledge.phone = "+998901234567"

        result = await EditorAgent().run(
            EditorRequest(
                business=make_business(), knowledge=knowledge, copy=copy,
                content_type=ContentType.FEED_POST, topic="IELTS", deep_check=True,
            )
        )

        assert not result.approved
        assert result.has_critical

    async def test_reflection_failure_still_returns_local_verdict(self, monkeypatch):
        from app.agents.editor import EditorAgent, EditorRequest
        from app.schemas.content import CopyOutput

        async def boom(self, prompt, schema, **kwargs):
            raise RuntimeError("gemini down")

        monkeypatch.setattr("app.services.gemini.GeminiClient.generate_structured", boom)
        monkeypatch.setattr("app.core.config.settings.gemini_api_key", "k", raising=False)

        knowledge = empty_knowledge()
        knowledge.phone = "+998901234567"
        copy = CopyOutput(
            caption_tg="Dars 2-sentabrda boshlanadi, telefon +998901234567 orqali bog'laning albatta",
            caption_ig="Dars 2-sentabrda boshlanadi, telefon +998901234567 orqali bog'laning albatta",
            cta="Qo'ng'iroq qiling",
        )

        result = await EditorAgent().run(
            EditorRequest(
                business=make_business(), knowledge=knowledge, copy=copy,
                content_type=ContentType.FEED_POST, topic="IELTS", deep_check=True,
            )
        )

        assert result.approved            # local rules found nothing wrong
        assert "o'tkazilmadi" in result.report.summary
