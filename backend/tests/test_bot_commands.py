"""Owner commands, the onboarding interview and voice handling."""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, Update, User, Voice

from app.models.business import Business, BusinessAdmin
from app.models.content_item import ContentItem
from app.models.content_plan import ContentPlan
from app.models.enums import (
    AdminRole,
    BusinessCategory,
    ContentItemStatus,
    ContentPillar,
    ContentPlanStatus,
    ContentType,
    Language,
    Platform,
    ToneOfVoice,
)
from app.models.knowledge_base import KnowledgeBase
from app.utils.dates import utcnow
from tests.test_bot_flows import MockedSession, make_update

pytestmark = pytest.mark.db

_IDS = itertools.count(2 * 10**9 + uuid.uuid4().int % 10**8)


@pytest.fixture
def owner_id() -> int:
    return next(_IDS)


@pytest.fixture
def bot():
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    return Bot(
        token="123456:AAHtestTokenForCommands",
        session=MockedSession(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest.fixture
def calls(bot) -> MockedSession:
    return bot.session


@pytest.fixture
def dispatcher(session_factory):
    from app.bot.main import build_dispatcher

    return build_dispatcher(storage=MemoryStorage(), session_factory=session_factory)


@pytest.fixture
async def business(session, owner_id: int) -> Business:
    entity = Business(
        name="Command Academy",
        slug=f"cmd-{uuid.uuid4().hex[:8]}",
        category=BusinessCategory.EDUCATION,
        tone_of_voice=ToneOfVoice.CASUAL,
        target_audience="18-30",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={"posts_per_week": 6},
    )
    session.add(entity)
    await session.flush()
    session.add_all(
        [
            BusinessAdmin(
                business_id=entity.id, telegram_user_id=owner_id, role=AdminRole.OWNER,
                receives_reviews=True,
            ),
            KnowledgeBase(business_id=entity.id, phone="+998901234567"),
        ]
    )
    await session.commit()
    return entity


def build_item(business_id, **overrides) -> ContentItem:
    item = ContentItem(
        business_id=business_id,
        content_type=ContentType.FEED_POST,
        pillar=ContentPillar.SALES,
        platform=Platform.TELEGRAM,
        topic="IELTS",
        headline="Sarlavha",
        hook="",
        cta="Yozing",
        caption_tg="Matn",
        caption_ig="",
        hashtags=[],
        carousel_slides=[],
        options={},
        script={},
        editor_report={},
        ai_meta={},
        scheduled_at=utcnow() + timedelta(days=1),
        status=ContentItemStatus.PENDING_REVIEW,
        quality_score=8.0,
        retry_count=0,
        regeneration_count=0,
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


class TestPlanCommand:
    @pytest.fixture(autouse=True)
    def no_broker(self, monkeypatch):
        """Exercise the inline path regardless of whether Redis is running."""
        monkeypatch.setattr("app.bot.handlers.admin.enqueue", lambda *a, **k: None)

    async def test_plan_sends_a_summary_and_previews(
        self, owner_id, dispatcher, bot, calls, session, business, monkeypatch
    ):
        from app.agents.orchestrator import PipelineResult

        created: dict[str, Any] = {}

        async def fake_generate_plan(self, business_id, **kwargs):
            plan = ContentPlan(
                business_id=business_id,
                title="Avgust intensivi",
                year=2026,
                week_number=41,
                month_number=10,
                starts_on=utcnow().date(),
                ends_on=utcnow().date() + timedelta(days=6),
                status=ContentPlanStatus.PENDING_REVIEW,
                strategy={"theme": "Avgust intensivi"},
                notes="",
            )
            plan.items = []
            self.session.add(plan)
            await self.session.flush()

            items = [build_item(business_id, headline=f"Post {i}") for i in range(4)]
            for item in items:
                plan.items.append(item)
            await self.session.flush()

            created["plan_id"] = plan.id
            return PipelineResult(plan=plan, items=items)

        monkeypatch.setattr(
            "app.agents.orchestrator.ContentPipeline.generate_plan", fake_generate_plan
        )

        await dispatcher.feed_update(bot, make_update(owner_id, "/plan"))

        texts = calls.texts()
        assert any("tayyorlanmoqda" in text for text in texts)
        assert any("Avgust intensivi" in text for text in texts)
        # Summary card + the first three posts.
        assert any("Post 0" in text for text in texts)
        assert any("Post 2" in text for text in texts)
        assert not any("Post 3" in text for text in texts)

    async def test_plan_failure_is_reported(
        self, owner_id, dispatcher, bot, calls, business, monkeypatch
    ):
        async def boom(self, business_id, **kwargs):
            raise RuntimeError("gemini quota exceeded")

        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.generate_plan", boom)

        await dispatcher.feed_update(bot, make_update(owner_id, "/plan"))
        assert any("Xatolik" in text or "AI xizmati" in text for text in calls.texts())

    async def test_plan_requires_membership(self, owner_id, dispatcher, bot, calls):
        await dispatcher.feed_update(bot, make_update(owner_id, "/plan"))
        assert "biriktirilmagansiz" in calls.texts()[-1]


class TestQuickCommand:
    @pytest.fixture(autouse=True)
    def no_broker(self, monkeypatch):
        monkeypatch.setattr("app.bot.handlers.admin.enqueue", lambda *a, **k: None)

    async def test_quick_post_flow(
        self, owner_id, dispatcher, bot, calls, session, business, monkeypatch
    ):
        async def fake_single(self, business_id, **kwargs):
            item = build_item(business_id, headline=f"Tezkor: {kwargs.get('topic', '')}")
            self.session.add(item)
            await self.session.flush()
            return item

        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.generate_single", fake_single)

        await dispatcher.feed_update(bot, make_update(owner_id, "/quick", update_id=1))
        assert "Qanday mavzuda" in calls.texts()[-1]

        await dispatcher.feed_update(bot, make_update(owner_id, "Sentabr chegirmasi", update_id=2))
        assert any("Tezkor: Sentabr chegirmasi" in text for text in calls.texts())

    async def test_quick_generation_error(
        self, owner_id, dispatcher, bot, calls, business, monkeypatch
    ):
        async def boom(self, business_id, **kwargs):
            raise RuntimeError("down")

        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.generate_single", boom)

        await dispatcher.feed_update(bot, make_update(owner_id, "/quick", update_id=1))
        await dispatcher.feed_update(bot, make_update(owner_id, "Mavzu", update_id=2))
        assert "Xatolik" in calls.texts()[-1]


class TestOnboardingInterview:
    @pytest.fixture(autouse=True)
    def stub_agent(self, monkeypatch):
        from app.agents.onboarding import OnboardingResult
        from app.schemas.knowledge_base import KnowledgeExtraction

        state = {"step": 0}

        async def fake_ingest(self, business_, knowledge, message, source="telegram"):
            state["step"] += 1
            knowledge.raw_notes = (knowledge.raw_notes or "") + message
            done = state["step"] >= 2
            return OnboardingResult(
                extraction=KnowledgeExtraction(),
                next_question=None if done else "Narxlar qanday?",
                completeness=1.0 if done else 0.4,
                updated_fields=["raw_notes"],
                summary=f"Qadam {state['step']} saqlandi",
            )

        monkeypatch.setattr("app.agents.onboarding.OnboardingAgent.ingest", fake_ingest)
        return state

    async def test_interview_walks_to_completion(self, owner_id, dispatcher, bot, calls, session):
        from sqlalchemy import select

        await dispatcher.feed_update(bot, make_update(owner_id, "/start", update_id=1))
        await dispatcher.feed_update(bot, make_update(owner_id, f"Markaz {uuid.uuid4().hex[:5]}", update_id=2))
        assert "Savol 1" in calls.texts()[-1]

        await dispatcher.feed_update(bot, make_update(owner_id, "IELTS va General English", update_id=3))
        assert "Narxlar qanday?" in calls.texts()[-1]

        await dispatcher.feed_update(bot, make_update(owner_id, "600 ming so'm", update_id=4))
        assert "Bilim bazasi tayyor" in calls.texts()[-1]

        admin = (
            await session.execute(
                select(BusinessAdmin).where(BusinessAdmin.telegram_user_id == owner_id)
            )
        ).scalars().one()
        knowledge = (
            await session.execute(
                select(KnowledgeBase).where(KnowledgeBase.business_id == admin.business_id)
            )
        ).scalars().one()
        assert "600 ming" in knowledge.raw_notes

    async def test_too_short_business_name_is_rejected(self, owner_id, dispatcher, bot, calls):
        await dispatcher.feed_update(bot, make_update(owner_id, "/start", update_id=1))
        await dispatcher.feed_update(bot, make_update(owner_id, "A", update_id=2))
        assert "to'liqroq" in calls.texts()[-1]


class TestVoiceHandling:
    def _voice_update(self, user_id: int, update_id: int = 1) -> Update:
        return Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.now(UTC),
                chat=Chat(id=user_id, type="private"),
                from_user=User(id=user_id, is_bot=False, first_name="Owner"),
                voice=Voice(file_id="f1", file_unique_id="u1", duration=3, mime_type="audio/ogg",
                            file_size=2048),
            ),
        )

    @pytest.fixture
    def stub_voice(self, monkeypatch):
        async def fake_download(bot_, message):
            return b"fake-audio-bytes", "audio/ogg"

        async def fake_transcribe(self, audio, *, filename="voice.ogg", mime_type="audio/ogg",
                                  language=None):
            assert audio == b"fake-audio-bytes"
            return "Narxni to'rt yuz ming qil"

        monkeypatch.setattr("app.bot.utils.download_voice", fake_download)
        monkeypatch.setattr(
            "app.services.transcription.TranscriptionService.transcribe", fake_transcribe
        )

    async def test_voice_note_is_transcribed_and_ingested(
        self, owner_id, dispatcher, bot, calls, business, stub_voice, monkeypatch
    ):
        from app.agents.onboarding import OnboardingResult
        from app.schemas.knowledge_base import KnowledgeExtraction

        seen: dict[str, str] = {}

        async def fake_ingest(self, business_, knowledge, message, source="telegram"):
            seen["message"] = message
            return OnboardingResult(
                extraction=KnowledgeExtraction(),
                next_question=None,
                completeness=0.6,
                updated_fields=["prices"],
                summary="Narx yangilandi",
            )

        monkeypatch.setattr("app.agents.onboarding.OnboardingAgent.ingest", fake_ingest)

        await dispatcher.feed_update(bot, self._voice_update(owner_id))

        assert seen["message"] == "Narxni to'rt yuz ming qil"
        texts = calls.texts()
        assert any("tinglanmoqda" in text for text in texts)
        assert any("Narx yangilandi" in text for text in texts)

    async def test_voice_edit_instruction_reaches_the_pipeline(
        self, owner_id, dispatcher, bot, calls, session, business, stub_voice, monkeypatch
    ):
        from app.bot.keyboards import ReviewCB
        from app.schemas.content import VoiceInstruction
        from tests.test_bot_flows import make_callback

        item = build_item(business.id)
        session.add(item)
        await session.commit()

        captured: dict[str, str] = {}

        async def fake_parse(self, message, item=None, tz_name=None):
            captured["heard"] = message
            return VoiceInstruction(
                action="change_price", instruction_for_writer="Narxni 400 ming qil", confidence=0.9
            )

        async def fake_regenerate(self, item_, *, instruction="", regenerate_image=False):
            captured["instruction"] = instruction
            return item_

        monkeypatch.setattr("app.agents.feedback.FeedbackAgent.parse", fake_parse)
        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.regenerate", fake_regenerate)

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="edit", item_id=item.id).pack(), update_id=1)
        )
        await dispatcher.feed_update(bot, self._voice_update(owner_id, update_id=2))

        assert captured["heard"] == "Narxni to'rt yuz ming qil"
        assert captured["instruction"] == "Narxni 400 ming qil"

    async def test_transcription_failure_is_reported(
        self, owner_id, dispatcher, bot, calls, business, monkeypatch
    ):
        async def fake_download(bot_, message):
            return b"audio", "audio/ogg"

        async def failing(self, audio, **kwargs):
            raise RuntimeError("whisper down")

        monkeypatch.setattr("app.bot.utils.download_voice", fake_download)
        monkeypatch.setattr("app.services.transcription.TranscriptionService.transcribe", failing)

        await dispatcher.feed_update(bot, self._voice_update(owner_id))
        assert any("o'girib bo'lmadi" in text for text in calls.texts())


class TestCancel:
    async def test_cancel_clears_the_active_flow(
        self, owner_id, dispatcher, bot, calls, business, monkeypatch
    ):
        await dispatcher.feed_update(bot, make_update(owner_id, "/quick", update_id=1))
        await dispatcher.feed_update(bot, make_update(owner_id, "/cancel", update_id=2))
        assert "Bekor qilindi" in calls.texts()[-1]

        # After cancelling, a plain message is knowledge input again, not a topic.
        async def fake_ingest(self, business_, knowledge, message, source="telegram"):
            from app.agents.onboarding import OnboardingResult
            from app.schemas.knowledge_base import KnowledgeExtraction

            return OnboardingResult(
                extraction=KnowledgeExtraction(), next_question=None, completeness=0.5,
                updated_fields=[], summary="Qabul qilindi",
            )

        monkeypatch.setattr("app.agents.onboarding.OnboardingAgent.ingest", fake_ingest)
        await dispatcher.feed_update(bot, make_update(owner_id, "Yangi ma'lumot", update_id=3))
        assert "Qabul qilindi" in calls.texts()[-1]


class TestGenerationIsOffloaded:
    """Chat handlers must hand long work to the worker, not run it inline."""

    async def test_plan_is_queued_when_a_broker_exists(
        self, owner_id, dispatcher, bot, calls, business, monkeypatch
    ):
        queued: list[tuple] = []
        monkeypatch.setattr(
            "app.bot.handlers.admin.enqueue",
            lambda name, *args, **kwargs: queued.append((name, args, kwargs)) or "task-1",
        )

        async def must_not_run(self, business_id, **kwargs):  # pragma: no cover
            raise AssertionError("generation must not run inside the bot process")

        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.generate_plan", must_not_run)

        await dispatcher.feed_update(bot, make_update(owner_id, "/plan"))

        assert queued and queued[0][0] == "app.tasks.generation.generate_weekly_plan"
        assert queued[0][2]["send_for_review"] is True
        assert any("tayyorlanmoqda" in text for text in calls.texts())

    async def test_plan_falls_back_to_inline_without_a_broker(
        self, owner_id, dispatcher, bot, calls, session, business, monkeypatch
    ):
        from app.agents.orchestrator import PipelineResult

        monkeypatch.setattr("app.bot.handlers.admin.enqueue", lambda *a, **k: None)

        ran = {"inline": False}

        async def fake_plan(self, business_id, **kwargs):
            ran["inline"] = True
            return PipelineResult(plan=None, items=[], failures=["quota"])

        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.generate_plan", fake_plan)

        await dispatcher.feed_update(bot, make_update(owner_id, "/plan"))
        assert ran["inline"] is True

    async def test_quick_post_is_queued(
        self, owner_id, dispatcher, bot, calls, business, monkeypatch
    ):
        queued: list[tuple] = []
        monkeypatch.setattr(
            "app.bot.handlers.admin.enqueue",
            lambda name, *args, **kwargs: queued.append((name, kwargs)) or "task-2",
        )

        await dispatcher.feed_update(bot, make_update(owner_id, "/quick", update_id=1))
        await dispatcher.feed_update(bot, make_update(owner_id, "Sentabr chegirmasi", update_id=2))

        assert queued and queued[0][0] == "app.tasks.generation.generate_single_item"
        assert queued[0][1]["topic"] == "Sentabr chegirmasi"


class TestRateLimitPatience:
    """How long a process waits on a provider backoff is configuration."""

    def _rate_limited(self, retry_after: float | None):
        from app.core.exceptions import RateLimitError

        error = RateLimitError("groq", "rate limited")
        error.retry_after = retry_after
        return error

    def test_chat_process_gives_up_on_a_long_wait(self, monkeypatch):
        from app.services.http import _is_retryable

        monkeypatch.setattr("app.core.config.settings.llm_max_retry_wait", 30.0, raising=False)
        assert _is_retryable(self._rate_limited(45.0)) is False

    def test_worker_waits_it_out(self, monkeypatch):
        from app.services.http import _is_retryable

        monkeypatch.setattr("app.core.config.settings.llm_max_retry_wait", 120.0, raising=False)
        assert _is_retryable(self._rate_limited(45.0)) is True

    def test_short_waits_are_always_retried(self, monkeypatch):
        from app.services.http import _is_retryable

        monkeypatch.setattr("app.core.config.settings.llm_max_retry_wait", 30.0, raising=False)
        assert _is_retryable(self._rate_limited(5.0)) is True
        assert _is_retryable(self._rate_limited(None)) is True
