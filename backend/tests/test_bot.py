"""Bot presentation layer: callback data, review cards, notifier fan-out."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.bot import texts
from app.bot.keyboards import BatchCB, BizCB, NavCB, ReviewCB, batch_keyboard, review_keyboard
from app.bot.review import format_review_caption, media_source, plan_list_text
from app.models.business import Business
from app.models.content_item import ContentItem
from app.models.content_plan import ContentPlan
from app.models.enums import (
    BusinessCategory,
    ContentItemStatus,
    ContentPillar,
    ContentPlanStatus,
    ContentType,
    Language,
    Platform,
    ToneOfVoice,
)
from app.utils.dates import utcnow
from app.utils.text import TG_CAPTION_LIMIT


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


def make_item(**overrides) -> ContentItem:
    item = ContentItem(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        content_type=ContentType.FEED_POST,
        pillar=ContentPillar.SALES,
        platform=Platform.BOTH,
        topic="IELTS intensiv",
        headline="IELTS 7.0 uch oyda",
        hook="",
        cta="Yozing",
        caption_tg="Post matni",
        caption_ig="Post matni",
        hashtags=["#ielts"],
        carousel_slides=[],
        options={},
        script={},
        editor_report={},
        ai_meta={},
        scheduled_at=utcnow() + timedelta(days=1),
        status=ContentItemStatus.PENDING_REVIEW,
        quality_score=8.4,
        retry_count=0,
        regeneration_count=0,
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


class TestCallbackData:
    def test_review_callback_round_trip(self):
        item_id = uuid.uuid4()
        packed = ReviewCB(action="approve", item_id=item_id).pack()
        unpacked = ReviewCB.unpack(packed)
        assert unpacked.action == "approve"
        assert unpacked.item_id == item_id

    def test_callback_payload_fits_telegram_limit(self):
        # Telegram rejects callback_data longer than 64 bytes.
        for factory in (
            ReviewCB(action="reschedule", item_id=uuid.uuid4()),
            BatchCB(action="approve_all", plan_id=uuid.uuid4()),
            BizCB(action="select", business_id=uuid.uuid4()),
            NavCB(action="finish_onboarding"),
        ):
            assert len(factory.pack().encode()) <= 64

    def test_review_keyboard_actions(self):
        item_id = uuid.uuid4()
        markup = review_keyboard(item_id)
        actions = {
            ReviewCB.unpack(button.callback_data).action
            for row in markup.inline_keyboard
            for button in row
        }
        assert actions == {"approve", "edit", "regen", "reschedule", "reject"}

    def test_batch_keyboard_shows_count(self):
        markup = batch_keyboard(uuid.uuid4(), 12)
        assert "12" in markup.inline_keyboard[0][0].text


class TestReviewCard:
    def test_caption_contains_metadata_and_body(self):
        item = make_item()
        caption = format_review_caption(item, make_business())
        assert "IELTS 7.0 uch oyda" in caption
        assert "8.4" in caption
        assert texts.pillar_label(ContentPillar.SALES) in caption
        assert "Post matni" in caption

    def test_caption_respects_telegram_limit(self):
        item = make_item(caption_tg="x" * 5000)
        assert len(format_review_caption(item, make_business())) <= TG_CAPTION_LIMIT

    def test_quiz_card_marks_the_correct_answer(self):
        item = make_item(
            content_type=ContentType.TELEGRAM_QUIZ,
            options={"question": "IELTS max?", "answers": ["9.0", "8.0"], "correct_option_id": 0,
                     "explanation": "Shunday"},
        )
        caption = format_review_caption(item, make_business())
        assert "✅ 9.0" in caption
        assert "▫️ 8.0" in caption

    def test_editor_warnings_surface(self):
        item = make_item(
            editor_report={"issues": [{"severity": "critical", "field": "cta", "problem": "CTA yo'q"}]}
        )
        assert "CTA yo'q" in format_review_caption(item, make_business())

    def test_reels_card_lists_scenes(self):
        item = make_item(
            content_type=ContentType.REELS_SCRIPT,
            script={"scenes": [{"t": "0-3s", "on_screen": "Hook matni"}]},
        )
        assert "Hook matni" in format_review_caption(item, make_business())


class TestMediaSource:
    def test_remote_url_is_passed_through(self):
        assert media_source("https://cdn.example.com/a.png") == "https://cdn.example.com/a.png"

    def test_none_returns_none(self):
        assert media_source(None) is None

    def test_local_file_is_uploaded_as_bytes(self, tmp_path, monkeypatch):
        from aiogram.types import FSInputFile

        from app.core.config import settings

        monkeypatch.setattr(settings, "media_root", tmp_path, raising=False)
        monkeypatch.setattr(settings, "public_base_url", "http://localhost:8000", raising=False)

        (tmp_path / "20260820").mkdir()
        target = tmp_path / "20260820" / "card.png"
        target.write_bytes(b"\x89PNG")

        source = media_source("http://localhost:8000/media/20260820/card.png")
        assert isinstance(source, FSInputFile)

    def test_missing_local_file_falls_back_to_url(self, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "media_root", tmp_path, raising=False)
        url = "http://localhost:8000/media/nope/missing.png"
        assert media_source(url) == url


class TestPlanList:
    def test_lists_every_item(self):
        plan = ContentPlan(
            id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            title="2026-W34",
            year=2026,
            week_number=34,
            month_number=8,
            starts_on=utcnow().date(),
            ends_on=utcnow().date(),
            status=ContentPlanStatus.PENDING_REVIEW,
            strategy={},
            notes="",
        )
        plan.items = [make_item(headline=f"Post {i}") for i in range(3)]
        text = plan_list_text(plan, make_business())
        assert "Post 0" in text and "Post 2" in text
        assert "2026-W34" in text


class TestTexts:
    def test_quality_bar_scales(self):
        assert texts.quality_bar(10) == "🟩🟩🟩🟩🟩"
        assert texts.quality_bar(0) == "⬜️⬜️⬜️⬜️⬜️"
        # "⬜️" is two code points, so count the squares rather than characters.
        def squares(bar: str) -> int:
            return bar.count("🟩") + bar.count("⬜")

        assert squares(texts.quality_bar(5)) == squares(texts.quality_bar(9)) == 5

    def test_labels_cover_every_enum_member(self):
        for pillar in ContentPillar:
            assert texts.pillar_label(pillar) != str(pillar)
        for content_type in ContentType:
            assert texts.type_label(content_type) != str(content_type)
        for status in ContentItemStatus:
            assert texts.status_label(status) != str(status)


class TestFeedbackFallback:
    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Bu postni bekor qil", "reject"),
            ("Qayta yaratib ber", "regenerate"),
            ("Vaqtni ertaga qil", "reschedule"),
            ("Narxni 400 ming qil", "change_price"),
            ("Rasmni almashtir", "change_image"),
            ("Birinchi qatorni kuchliroq yoz", "edit_caption"),
        ],
    )
    def test_keyword_intents(self, message: str, expected: str):
        from app.agents.feedback import FeedbackAgent

        assert FeedbackAgent.keyword_fallback(message).action == expected


class TestOnboardingProgress:
    def test_progress_bar_reflects_score(self):
        from app.agents.onboarding import OnboardingAgent
        from app.models.knowledge_base import KnowledgeBase

        knowledge = KnowledgeBase(
            key_offerings=[], prices=[], usps=[], teacher_profiles=[], faq=[],
            success_stories=[], raw_notes="", banned_topics=[], preferred_hashtags=[],
            competitors=[], brand_colors={},
        )
        knowledge.compute_completeness()
        assert "0%" in OnboardingAgent.progress_text(knowledge)

    def test_next_question_follows_the_script(self):
        from app.agents.onboarding import INTERVIEW_QUESTIONS, OnboardingAgent
        from app.models.knowledge_base import KnowledgeBase

        knowledge = KnowledgeBase(
            key_offerings=[], prices=[], usps=[], teacher_profiles=[], faq=[],
            success_stories=[], raw_notes="", banned_topics=[], preferred_hashtags=[],
            competitors=[], brand_colors={},
        )
        assert OnboardingAgent.fallback_question(knowledge) == INTERVIEW_QUESTIONS[0][1]


class TestNotifier:
    async def test_push_items_notifies_every_reviewer(self, session, monkeypatch):
        """A stubbed bot session lets us verify fan-out without Telegram."""
        import contextlib

        from app.models.business import BusinessAdmin
        from app.models.enums import AdminRole

        business = make_business()
        business.slug = f"notify-{utcnow().timestamp()}"
        session.add(business)
        await session.flush()

        session.add_all(
            [
                BusinessAdmin(business_id=business.id, telegram_user_id=111, role=AdminRole.OWNER,
                              receives_reviews=True),
                BusinessAdmin(business_id=business.id, telegram_user_id=222, role=AdminRole.MANAGER,
                              receives_reviews=True),
                BusinessAdmin(business_id=business.id, telegram_user_id=333, role=AdminRole.VIEWER,
                              receives_reviews=False),
            ]
        )
        item = make_item(business_id=business.id)
        session.add(item)
        await session.flush()

        sent: list[int] = []

        @contextlib.asynccontextmanager
        async def fake_bot_session(token=None):
            yield object()

        async def fake_send(bot, item_, business_, chat_id):
            sent.append(chat_id)
            return 900 + len(sent)

        monkeypatch.setattr("app.bot.notifier.bot_session", fake_bot_session)
        monkeypatch.setattr("app.bot.notifier.send_item_for_review", fake_send)

        from app.bot.notifier import push_items_for_review

        count = await push_items_for_review(session, business, [item])

        assert count == 2
        assert set(sent) == {111, 222}      # the viewer is excluded
        assert item.sent_for_review is True
        assert item.review_chat_id == 111

    async def test_push_is_skipped_without_a_bot_token(self, session, monkeypatch):
        import contextlib

        from app.core.exceptions import ConfigurationError

        business = make_business()
        business.slug = f"notoken-{utcnow().timestamp()}"
        session.add(business)
        await session.flush()

        from app.models.business import BusinessAdmin
        from app.models.enums import AdminRole

        session.add(
            BusinessAdmin(business_id=business.id, telegram_user_id=1, role=AdminRole.OWNER,
                          receives_reviews=True)
        )
        await session.flush()

        @contextlib.asynccontextmanager
        async def failing_session(token=None):
            raise ConfigurationError("no token")
            yield  # pragma: no cover

        monkeypatch.setattr("app.bot.notifier.bot_session", failing_session)

        from app.bot.notifier import push_items_for_review

        assert await push_items_for_review(session, business, [make_item()]) == 0
