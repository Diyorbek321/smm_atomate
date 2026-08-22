"""Agent logic that must hold without touching any external API."""

from __future__ import annotations

import pytest

from app.agents.editor import EditorAgent, EditorRequest
from app.agents.strategist import allocate_pillars, default_content_type
from app.models.business import Business
from app.models.enums import (
    PILLAR_CONTENT_TYPES,
    PILLAR_DISTRIBUTION,
    BusinessCategory,
    ContentPillar,
    ContentType,
    Language,
    Plan,
    ToneOfVoice,
)
from app.models.knowledge_base import KnowledgeBase
from app.schemas.content import CopyOutput


def make_business(plan: Plan = Plan.PRO, **overrides) -> Business:
    """Pro by default so agent tests exercise the full content-type range."""
    return Business(
        name="Bright Academy",
        plan=plan,
        category=BusinessCategory.EDUCATION,
        tone_of_voice=ToneOfVoice.CASUAL,
        target_audience="18-30",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={},
        **overrides,
    )


def make_knowledge(**overrides) -> KnowledgeBase:
    knowledge = KnowledgeBase(
        key_offerings=[{"name": "IELTS intensiv"}],
        prices=[{"item": "IELTS intensiv", "price": 600000, "currency": "UZS"}],
        usps=["8.0 IELTS o'qituvchisi"],
        teacher_profiles=[],
        faq=[],
        success_stories=[],
        raw_notes="",
        banned_topics=[],
        preferred_hashtags=[],
        competitors=[],
        brand_colors={},
        phone="+998901234567",
        telegram_username="brightacademy",
    )
    for key, value in overrides.items():
        setattr(knowledge, key, value)
    return knowledge


class TestPillarAllocation:
    @pytest.mark.parametrize("total", [4, 7, 10, 12, 20, 30, 31])
    def test_counts_sum_to_total(self, total: int):
        allocation = allocate_pillars(total)
        assert sum(allocation.values()) == total

    @pytest.mark.parametrize("total", [4, 8, 12, 20])
    def test_every_pillar_is_represented(self, total: int):
        allocation = allocate_pillars(total)
        assert all(count >= 1 for count in allocation.values())

    def test_ratio_is_within_one_post_of_target(self):
        total = 20
        allocation = allocate_pillars(total)
        for pillar, share in PILLAR_DISTRIBUTION.items():
            assert abs(allocation[pillar] - share * total) <= 1

    def test_sales_and_education_lead(self):
        allocation = allocate_pillars(10)
        assert allocation[ContentPillar.SALES] == 3
        assert allocation[ContentPillar.EDUCATIONAL] == 3
        assert allocation[ContentPillar.SOCIAL_PROOF] == 3   # 2.5 rounds up
        assert allocation[ContentPillar.INTERACTIVE] == 1

    def test_zero_and_negative(self):
        assert sum(allocate_pillars(0).values()) == 0
        assert sum(allocate_pillars(-5).values()) == 0

    def test_content_type_rotation_stays_valid(self):
        for pillar in ContentPillar:
            for index in range(6):
                assert default_content_type(pillar, index) in PILLAR_CONTENT_TYPES[pillar]

    def test_custom_ratios_from_business_settings(self):
        from app.agents.strategist import pillar_ratios_for
        from app.models.business import Business
        from app.models.enums import BusinessCategory

        business = Business(
            name="B", category=BusinessCategory.EDUCATION,
            settings={"pillar_ratios": {"sales": 0.25, "educational": 0.5,
                                        "social_proof": 0.125, "interactive": 0.125}},
        )
        ratios = pillar_ratios_for(business)
        allocation = allocate_pillars(8, ratios)
        # "har 4 postdan 1 tasi sotuv": 8 post = 2 sotuv + 6 ma'lumot
        assert allocation[ContentPillar.SALES] == 2
        assert allocation[ContentPillar.EDUCATIONAL] == 4
        assert allocation[ContentPillar.SOCIAL_PROOF] == 1
        assert allocation[ContentPillar.INTERACTIVE] == 1
        assert sum(allocation.values()) == 8

    def test_broken_ratio_settings_fall_back_to_default(self):
        from app.agents.strategist import pillar_ratios_for
        from app.models.business import Business
        from app.models.enums import BusinessCategory

        for bad in ({}, {"pillar_ratios": "hammasi sotuv"}, {"pillar_ratios": {"sales": -1}},
                    {"pillar_ratios": {"nonexistent": 1.0}}):
            business = Business(name="B", category=BusinessCategory.EDUCATION, settings=bad)
            assert pillar_ratios_for(business) == dict(PILLAR_DISTRIBUTION)


class TestEditorStaticChecks:
    def _run(self, copy: CopyOutput, content_type=ContentType.FEED_POST, knowledge=None):
        agent = EditorAgent()
        request = EditorRequest(
            business=make_business(),
            knowledge=knowledge if knowledge is not None else make_knowledge(),
            copy=copy,
            content_type=content_type,
            topic="IELTS",
            deep_check=False,
        )
        return agent.static_checks(request)

    def test_clean_post_has_no_critical_issues(self):
        copy = CopyOutput(
            caption_tg="IELTS 7.0 olish uchun uchta odatni o'zgartiring. Birinchisi — har kuni 30 daqiqa "
            "listening. Batafsil: +998901234567",
            caption_ig="IELTS 7.0 olish uchun uchta odatni o'zgartiring. Batafsil: +998901234567",
            cta="Bepul darsga yozilish uchun +998901234567 ga qo'ng'iroq qiling",
            hashtags=["#ielts", "#toshkent"],
        )
        issues = self._run(copy)
        assert not [i for i in issues if i.severity == "critical"]

    def test_empty_caption_is_critical(self):
        issues = self._run(CopyOutput(caption_tg="", caption_ig="", cta="Yozing"))
        assert any(i.severity == "critical" for i in issues)

    def test_placeholder_is_critical(self):
        copy = CopyOutput(
            caption_tg="IELTS kursi narxi [narx] so'm, batafsil +998901234567 raqamiga qo'ng'iroq qiling bugun",
            caption_ig="IELTS kursi narxi [narx] so'm, batafsil +998901234567 raqamiga qo'ng'iroq qiling bugun",
            cta="Qo'ng'iroq qiling",
        )
        issues = self._run(copy)
        assert any("narx" in i.problem for i in issues if i.severity == "critical")

    def test_missing_cta_flagged(self):
        copy = CopyOutput(
            caption_tg="IELTS haqida foydali maslahat, telefon +998901234567 orqali bog'laning albatta",
            caption_ig="IELTS haqida foydali maslahat, telefon +998901234567 orqali bog'laning albatta",
            cta="",
        )
        assert any(i.field == "cta" for i in self._run(copy))

    def test_missing_contact_flagged(self):
        copy = CopyOutput(
            caption_tg="IELTS haqida juda foydali maslahatlar to'plami sizga yordam beradi albatta bugun",
            caption_ig="IELTS haqida juda foydali maslahatlar to'plami sizga yordam beradi albatta bugun",
            cta="Yozing",
        )
        issues = self._run(copy)
        assert any("Aloqa" in i.problem for i in issues)

    def test_banned_topic_is_critical(self):
        knowledge = make_knowledge(banned_topics=["siyosat"])
        copy = CopyOutput(
            caption_tg="Bugun siyosat haqida gaplashamiz va IELTS ni ham eslaymiz +998901234567 bilan",
            caption_ig="Bugun siyosat haqida gaplashamiz va IELTS ni ham eslaymiz +998901234567 bilan",
            cta="Yozing",
        )
        issues = self._run(copy, knowledge=knowledge)
        assert any(i.severity == "critical" and "siyosat" in i.problem for i in issues)

    def test_banned_topic_does_not_fire_inside_words(self):
        """`din` must not match inside `farzandining` — whole words only."""
        knowledge = make_knowledge(banned_topics=["din"])
        copy = CopyOutput(
            caption_tg="Farzandining natijasini tezlashtirmoqchi bo'lgan ota-onalarga maslahat +998901234567",
            caption_ig="Farzandining natijasini tezlashtirmoqchi bo'lgan ota-onalarga maslahat +998901234567",
            cta="Qo'ng'iroq qiling",
        )
        issues = self._run(copy, knowledge=knowledge)
        assert not any("din" in i.problem for i in issues if i.severity == "critical")

        copy_bad = CopyOutput(
            caption_tg="Bugun din haqida gaplashamiz, aloqa +998901234567 orqali bog'lanasiz albatta",
            caption_ig="Bugun din haqida gaplashamiz, aloqa +998901234567 orqali bog'lanasiz albatta",
            cta="Yozing",
        )
        issues = self._run(copy_bad, knowledge=knowledge)
        assert any(i.severity == "critical" and "din" in i.problem for i in issues)

    def test_carousel_needs_slides(self):
        copy = CopyOutput(
            caption_tg="IELTS bo'yicha 5 ta maslahat, batafsil +998901234567 raqamiga yozing bugunoq albatta",
            caption_ig="IELTS bo'yicha 5 ta maslahat, batafsil +998901234567 raqamiga yozing bugunoq albatta",
            cta="Yozing",
            slides=[{"index": 1, "title": "Bir"}],
        )
        issues = self._run(copy, ContentType.CAROUSEL)
        assert any(i.field == "slides" and i.severity == "critical" for i in issues)

    def test_quiz_needs_valid_answer_index(self):
        copy = CopyOutput(
            caption_tg="Savolga javob bering va bilimingizni tekshiring +998901234567 orqali bog'laning",
            caption_ig="Savolga javob bering va bilimingizni tekshiring +998901234567 orqali bog'laning",
            cta="Javob bering",
            quiz={"question": "IELTS max ball?", "answers": ["9.0", "10.0"], "correct_option_id": 7},
        )
        issues = self._run(copy, ContentType.TELEGRAM_QUIZ)
        assert any(i.field == "quiz" and i.severity == "critical" for i in issues)

    def test_too_many_hashtags(self):
        copy = CopyOutput(
            caption_tg="IELTS kursimizga yoziling, batafsil ma'lumot uchun +998901234567 raqamiga qo'ng'iroq",
            caption_ig="IELTS kursimizga yoziling, batafsil ma'lumot uchun +998901234567 raqamiga qo'ng'iroq",
            cta="Yozing",
            hashtags=[f"#tag{i}" for i in range(35)],
        )
        assert any(i.field == "hashtags" for i in self._run(copy))


class TestKnowledgeBaseModel:
    def test_completeness_grows_with_data(self):
        empty = KnowledgeBase(
            key_offerings=[], prices=[], usps=[], teacher_profiles=[], faq=[], success_stories=[],
            raw_notes="", banned_topics=[], preferred_hashtags=[], competitors=[], brand_colors={},
        )
        assert empty.compute_completeness() == 0.0

        filled = make_knowledge(
            faq=[{"q": "a", "a": "b"}],
            teacher_profiles=[{"name": "Aziz"}],
            raw_notes="x" * 60,
        )
        assert filled.compute_completeness() > 0.9

    def test_missing_fields_listed(self):
        knowledge = make_knowledge(prices=[], usps=[])
        missing = knowledge.missing_fields
        assert "prices" in missing and "usps" in missing
        assert "key_offerings" not in missing

    def test_contact_line_formats(self):
        knowledge = make_knowledge(address="Chilonzor 5")
        line = knowledge.contact_line
        assert "+998901234567" in line and "@brightacademy" in line and "Chilonzor" in line

    def test_prompt_context_is_json(self):
        import json

        payload = json.loads(make_knowledge().to_prompt_context())
        assert payload["contacts"]["phone"] == "+998901234567"


class TestOnboardingMerge:
    def test_merge_updates_existing_price(self):
        from app.agents.onboarding import OnboardingAgent
        from app.schemas.knowledge_base import KnowledgeExtraction, PriceItem

        knowledge = make_knowledge()
        extraction = KnowledgeExtraction(
            prices=[PriceItem(item="IELTS intensiv", price=400000, currency="UZS")]
        )
        updated = OnboardingAgent.merge(knowledge, extraction, raw_message="narxni 400 ming qil")

        assert "prices" in updated
        assert len(knowledge.prices) == 1
        assert knowledge.prices[0]["price"] == 400000

    def test_merge_appends_new_offering(self):
        from app.agents.onboarding import OnboardingAgent
        from app.schemas.knowledge_base import KnowledgeExtraction, Offering

        knowledge = make_knowledge()
        OnboardingAgent.merge(knowledge, KnowledgeExtraction(key_offerings=[Offering(name="SAT")]))
        names = {o["name"] for o in knowledge.key_offerings}
        assert names == {"IELTS intensiv", "SAT"}

    def test_merge_never_drops_data(self):
        from app.agents.onboarding import OnboardingAgent
        from app.schemas.knowledge_base import KnowledgeExtraction

        knowledge = make_knowledge()
        before = len(knowledge.usps)
        OnboardingAgent.merge(knowledge, KnowledgeExtraction())
        assert len(knowledge.usps) == before
        assert knowledge.prices


class TestCopywriterPostProcessing:
    def test_cta_and_contacts_are_appended(self):
        from app.agents.copywriter import CopyRequest, CopywriterAgent

        agent = CopywriterAgent()
        request = CopyRequest(
            business=make_business(),
            knowledge=make_knowledge(),
            content_type=ContentType.FEED_POST,
            pillar=ContentPillar.SALES,
            topic="IELTS",
        )
        copy = agent._post_process(
            CopyOutput(
                caption_tg="Matn",
                caption_ig="",
                cta="Hoziroq yozing",
                hashtags=["ielts", "#ielts"],
            ),
            request,
        )
        assert "Hoziroq yozing" in copy.caption_tg
        assert "+998901234567" in copy.caption_tg
        assert copy.caption_ig            # mirrored from TG
        assert copy.hashtags == ["#ielts"]

    def test_quiz_normalisation_clamps_index(self):
        from app.agents.copywriter import CopyRequest, CopywriterAgent

        request = CopyRequest(
            business=make_business(),
            knowledge=make_knowledge(),
            content_type=ContentType.TELEGRAM_QUIZ,
            pillar=ContentPillar.INTERACTIVE,
            topic="IELTS",
        )
        quiz = CopywriterAgent._normalize_quiz(
            {"question": "Savol", "answers": ["a", "b"], "correct_option_id": 9}, request
        )
        assert quiz["correct_option_id"] == 0

    def test_carousel_slides_are_indexed(self):
        from app.agents.copywriter import CopyRequest, CopywriterAgent

        request = CopyRequest(
            business=make_business(),
            knowledge=make_knowledge(),
            content_type=ContentType.CAROUSEL,
            pillar=ContentPillar.EDUCATIONAL,
            topic="IELTS",
        )
        slides = CopywriterAgent._normalize_slides(
            [{"title": "A", "body": "x"}, {"title": "", "body": ""}, {"title": "B", "body": "y"}], request
        )
        assert [s["index"] for s in slides] == [1, 2]


class TestContactNormalisation:
    """Models keep filing phone numbers under `telegram_username`."""

    def _kb(self, **overrides) -> KnowledgeBase:
        knowledge = make_knowledge(phone=None, telegram_username=None, instagram_username=None)
        for key, value in overrides.items():
            setattr(knowledge, key, value)
        return knowledge

    def test_phone_in_the_username_field_is_moved(self):
        from app.agents.onboarding import normalise_contacts

        knowledge = self._kb(telegram_username="+998931913308")
        fixed = normalise_contacts(knowledge)

        assert knowledge.phone == "+998931913308"
        assert knowledge.telegram_username is None
        assert "phone" in fixed

    def test_spaced_and_dashed_numbers_are_recognised(self):
        from app.agents.onboarding import looks_like_phone

        for value in ("+998 93 191 33 08", "998931913308", "93-191-33-08", "(93) 191 33 08"):
            assert looks_like_phone(value), value

    def test_handles_are_not_mistaken_for_phones(self):
        from app.agents.onboarding import looks_like_phone

        for value in ("bright_ielts", "@markaz_uz", "shanghai2024", ""):
            assert not looks_like_phone(value), value

    def test_at_prefix_is_stripped_from_handles(self):
        from app.agents.onboarding import normalise_contacts

        knowledge = self._kb(telegram_username="@markaz_uz", instagram_username="@markaz.uz")
        normalise_contacts(knowledge)

        assert knowledge.telegram_username == "markaz_uz"
        assert knowledge.instagram_username == "markaz.uz"

    def test_handle_stored_as_phone_is_moved_back(self):
        from app.agents.onboarding import normalise_contacts

        knowledge = self._kb(phone="@markaz_uz")
        normalise_contacts(knowledge)

        assert knowledge.telegram_username == "markaz_uz"
        assert knowledge.phone is None

    def test_correct_values_are_left_alone(self):
        from app.agents.onboarding import normalise_contacts

        knowledge = self._kb(phone="+998901234567", telegram_username="markaz_uz")
        assert normalise_contacts(knowledge) == []
        assert knowledge.phone == "+998901234567"
        assert knowledge.telegram_username == "markaz_uz"

    def test_merge_repairs_contacts_end_to_end(self):
        from app.agents.onboarding import OnboardingAgent
        from app.schemas.knowledge_base import KnowledgeExtraction

        knowledge = self._kb()
        OnboardingAgent.merge(knowledge, KnowledgeExtraction(telegram_username="+998931913308"))

        assert knowledge.phone == "+998931913308"
        assert knowledge.telegram_username is None
        assert "📞 +998931913308" in knowledge.contact_line
