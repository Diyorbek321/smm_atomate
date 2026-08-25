"""Approval flows driven through the real aiogram dispatcher.

A mocked Bot session records every outbound API call, so the whole chain —
middlewares, FSM, filters, handlers, database writes — runs for real.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User, Video

from app.bot.keyboards import BatchCB, ReviewCB
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
    Plan,
    Platform,
    ToneOfVoice,
)
from app.utils.dates import utcnow

pytestmark = pytest.mark.db

#: Each test gets its own Telegram identity — unique per run, because the test
#: database is not wiped between runs and an admin row would otherwise make an
#: earlier run's business the "active" one.
_NEXT_OWNER_ID = itertools.count(10**9 + uuid.uuid4().int % 10**8)


class MockedSession(BaseSession):
    """Answers every Bot API call locally and records what was sent."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._message_id = 1000

    @property
    def names(self) -> list[str]:
        return [type(call).__name__ for call in self.calls]

    def texts(self) -> list[str]:
        out = []
        for call in self.calls:
            for attr in ("text", "caption"):
                value = getattr(call, attr, None)
                if value:
                    out.append(value)
        return out

    def last_of(self, method_name: str) -> Any:
        for call in reversed(self.calls):
            if type(call).__name__ == method_name:
                return call
        return None

    def _message(self, bot: Bot | None = None) -> Message:
        self._message_id += 1
        message = Message(
            message_id=self._message_id,
            date=datetime.now(UTC),
            chat=Chat(id=1, type="private"),
        )
        # Handlers call .edit_text()/.answer() on returned messages, which needs
        # the object bound to a bot instance — exactly as the real API returns it.
        return message.as_(bot) if bot is not None else message

    async def close(self) -> None:  # pragma: no cover - nothing to close
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> Any:
        self.calls.append(method)
        name = type(method).__name__
        if name == "SendMediaGroup":
            return [self._message(bot), self._message(bot)]
        if name in {"AnswerCallbackQuery", "DeleteWebhook", "SetMyCommands"}:
            return True
        if name.startswith("Edit"):
            return self._message(bot)
        if name == "GetMe":
            return User(id=bot.id, is_bot=True, first_name="AutoSMM")
        return self._message(bot)

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        yield b""


@pytest.fixture
def owner_id() -> int:
    return next(_NEXT_OWNER_ID)


@pytest.fixture
def bot() -> Bot:
    return Bot(
        token="123456:AAHtestTokenForDispatcherFlows",
        session=MockedSession(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest.fixture
def session_calls(bot: Bot) -> MockedSession:
    return bot.session  # type: ignore[return-value]


@pytest.fixture
def dispatcher(session_factory):
    from app.bot.main import build_dispatcher

    return build_dispatcher(storage=MemoryStorage(), session_factory=session_factory)


def make_update(user_id: int, text: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Owner"),
            text=text,
        ),
    )


def make_video_update(
    user_id: int, update_id: int = 1, *, duration: int = 12, size: int = 2 * 1024 * 1024
) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Owner"),
            video=Video(
                file_id=f"vid-{update_id}",
                file_unique_id=f"u{update_id}",
                width=1080,
                height=1920,
                duration=duration,
                file_size=size,
                file_name="dars.mp4",
            ),
        ),
    )


def make_callback(user_id: int, data: str, update_id: int = 1, *, with_photo: bool = False) -> Update:
    message = Message(
        message_id=500 + update_id,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=True, first_name="AutoSMM"),
        text=None if with_photo else "Review card",
        caption="Review card" if with_photo else None,
    )
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=User(id=user_id, is_bot=False, first_name="Owner"),
            chat_instance="ci",
            message=message,
            data=data,
        ),
    )


@pytest.fixture
async def owned_business(session, owner_id: int) -> Business:
    business = Business(
        name="Flow Academy",
        slug=f"flow-{uuid.uuid4().hex[:8]}",
        category=BusinessCategory.EDUCATION,
        tone_of_voice=ToneOfVoice.CASUAL,
        target_audience="18-30",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={},
    )
    session.add(business)
    await session.flush()
    session.add(
        BusinessAdmin(
            business_id=business.id,
            telegram_user_id=owner_id,
            full_name="Owner",
            role=AdminRole.OWNER,
            receives_reviews=True,
        )
    )
    from app.models.knowledge_base import KnowledgeBase

    session.add(KnowledgeBase(business_id=business.id))
    await session.commit()
    return business


def make_item(business_id, **overrides) -> ContentItem:
    item = ContentItem(
        business_id=business_id,
        content_type=ContentType.FEED_POST,
        pillar=ContentPillar.SALES,
        platform=Platform.TELEGRAM,
        topic="IELTS",
        headline="IELTS 7.0 uch oyda",
        hook="",
        cta="Yozing",
        caption_tg="Telegram matni",
        caption_ig="",
        hashtags=[],
        carousel_slides=[],
        options={},
        script={},
        editor_report={},
        ai_meta={},
        scheduled_at=utcnow() + timedelta(days=1),
        status=ContentItemStatus.PENDING_REVIEW,
        quality_score=8.2,
        retry_count=0,
        regeneration_count=0,
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


class TestStartAndMenu:
    async def test_known_owner_sees_the_menu(self, owner_id: int, dispatcher, bot, session_calls, owned_business):
        await dispatcher.feed_update(bot, make_update(owner_id, "/start"))

        assert "SendMessage" in session_calls.names
        text = session_calls.texts()[0]
        assert owned_business.name in text
        assert "Bilim bazasi" in text

    async def test_unknown_user_is_asked_for_a_business_name(self, owner_id: int, dispatcher, bot, session_calls):
        # `owner_id` is unused as an admin here — the user belongs to no business.
        await dispatcher.feed_update(bot, make_update(owner_id, "/start"))
        assert "biznesingiz nomini yozing" in session_calls.texts()[0].lower()

    async def test_new_user_creates_a_business_and_starts_the_interview(
        self, owner_id: int, dispatcher, bot, session_calls, session
    ):
        from sqlalchemy import select

        stranger = owner_id
        name = f"Yangi Markaz {uuid.uuid4().hex[:6]}"
        await dispatcher.feed_update(bot, make_update(stranger, "/start", update_id=1))
        await dispatcher.feed_update(bot, make_update(stranger, name, update_id=2))

        created = (
            await session.execute(select(Business).where(Business.name == name))
        ).scalars().first()
        assert created is not None

        admins = (
            await session.execute(
                select(BusinessAdmin).where(BusinessAdmin.telegram_user_id == stranger)
            )
        ).scalars().all()
        assert len(admins) == 1
        assert "Savol 1" in session_calls.texts()[-1]

    async def test_help_command(self, owner_id: int, dispatcher, bot, session_calls, owned_business):
        await dispatcher.feed_update(bot, make_update(owner_id, "/help"))
        assert "/plan" in session_calls.texts()[0]


class TestReviewActions:
    async def test_approve_button_marks_the_item_approved(
        self, owner_id: int, dispatcher, bot, session_calls, session, owned_business
    ):
        item = make_item(owned_business.id)
        session.add(item)
        await session.commit()

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="approve", item_id=item.id).pack())
        )

        await session.refresh(item)
        assert item.status == ContentItemStatus.APPROVED
        assert item.reviewed_by == owner_id
        assert item.reviewed_at is not None
        assert "AnswerCallbackQuery" in session_calls.names
        assert "Tasdiqlandi" in (session_calls.last_of("EditMessageText").text or "")

    async def test_reject_button(self, owner_id: int, dispatcher, bot, session, owned_business):
        item = make_item(owned_business.id)
        session.add(item)
        await session.commit()

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="reject", item_id=item.id).pack())
        )

        await session.refresh(item)
        assert item.status == ContentItemStatus.REJECTED

    async def test_approving_twice_is_reported_not_repeated(
        self, owner_id: int, dispatcher, bot, session_calls, session, owned_business
    ):
        item = make_item(owned_business.id, status=ContentItemStatus.PUBLISHED)
        session.add(item)
        await session.commit()

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="approve", item_id=item.id).pack())
        )
        answer = session_calls.last_of("AnswerCallbackQuery")
        assert answer.show_alert is True
        assert "ko'rib chiqilgan" in answer.text

        await session.refresh(item)
        assert item.status == ContentItemStatus.PUBLISHED

    async def test_item_of_another_business_is_not_touchable(
        self, owner_id: int, dispatcher, bot, session_calls, session, owned_business
    ):
        other = Business(
            name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", category=BusinessCategory.RETAIL,
            tone_of_voice=ToneOfVoice.BOLD, target_audience="", language=Language.UZ,
            timezone="Asia/Tashkent", settings={},
        )
        session.add(other)
        await session.flush()
        item = make_item(other.id)
        session.add(item)
        await session.commit()

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="approve", item_id=item.id).pack())
        )

        await session.refresh(item)
        assert item.status == ContentItemStatus.PENDING_REVIEW
        assert session_calls.last_of("AnswerCallbackQuery").show_alert is True

    async def test_reschedule_flow_updates_the_time(
        self, owner_id: int, dispatcher, bot, session_calls, session, owned_business
    ):
        item = make_item(owned_business.id)
        session.add(item)
        await session.commit()
        original = item.scheduled_at

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="reschedule", item_id=item.id).pack(), update_id=1)
        )
        assert "Yangi vaqtni yuboring" in session_calls.texts()[-1]

        await dispatcher.feed_update(bot, make_update(owner_id, "25.12.2030 18:00", update_id=2))

        await session.refresh(item)
        assert item.scheduled_at != original
        assert item.scheduled_at.year == 2030
        assert "Vaqt yangilandi" in session_calls.texts()[-1]

    async def test_reschedule_rejects_garbage_and_keeps_asking(
        self, owner_id: int, dispatcher, bot, session_calls, session, owned_business
    ):
        item = make_item(owned_business.id)
        session.add(item)
        await session.commit()

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="reschedule", item_id=item.id).pack(), update_id=1)
        )
        await dispatcher.feed_update(bot, make_update(owner_id, "ertaga kechqurun", update_id=2))

        assert "Format:" in session_calls.texts()[-1]

    async def test_edit_flow_regenerates_with_the_instruction(
        self, owner_id: int, dispatcher, bot, session_calls, session, owned_business, monkeypatch
    ):
        item = make_item(owned_business.id)
        session.add(item)
        await session.commit()

        captured: dict[str, Any] = {}

        from app.schemas.content import VoiceInstruction

        async def fake_parse(self, message, item=None, tz_name=None):
            captured["message"] = message
            return VoiceInstruction(
                action="change_price", instruction_for_writer="Narxni 400 ming qil", confidence=0.9
            )

        async def fake_regenerate(self, item_, *, instruction="", regenerate_image=False):
            captured["instruction"] = instruction
            item_.caption_tg = "Yangilangan matn 400 ming"
            item_.regeneration_count += 1
            return item_

        monkeypatch.setattr("app.agents.feedback.FeedbackAgent.parse", fake_parse)
        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.regenerate", fake_regenerate)

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="edit", item_id=item.id).pack(), update_id=1)
        )
        assert "Nimani o'zgartiray" in session_calls.texts()[-1]

        await dispatcher.feed_update(bot, make_update(owner_id, "Narxni 400 ming qil", update_id=2))

        assert captured["message"] == "Narxni 400 ming qil"
        assert captured["instruction"] == "Narxni 400 ming qil"

        await session.refresh(item)
        assert item.caption_tg == "Yangilangan matn 400 ming"
        assert item.review_notes == "Narxni 400 ming qil"

    async def test_voice_instruction_can_reject_the_post(
        self, owner_id: int, dispatcher, bot, session, owned_business, monkeypatch
    ):
        item = make_item(owned_business.id)
        session.add(item)
        await session.commit()

        from app.schemas.content import VoiceInstruction

        async def fake_parse(self, message, item=None, tz_name=None):
            return VoiceInstruction(action="reject", confidence=0.9)

        monkeypatch.setattr("app.agents.feedback.FeedbackAgent.parse", fake_parse)

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="edit", item_id=item.id).pack(), update_id=1)
        )
        await dispatcher.feed_update(bot, make_update(owner_id, "Bu post kerakmas", update_id=2))

        await session.refresh(item)
        assert item.status == ContentItemStatus.REJECTED

    async def test_regenerate_button_runs_the_pipeline(
        self, owner_id: int, dispatcher, bot, session_calls, session, owned_business, monkeypatch
    ):
        item = make_item(owned_business.id)
        session.add(item)
        await session.commit()

        async def fake_regenerate(self, item_, *, instruction="", regenerate_image=False):
            item_.headline = "Butunlay yangi sarlavha"
            item_.regeneration_count += 1
            return item_

        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.regenerate", fake_regenerate)

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="regen", item_id=item.id).pack())
        )

        await session.refresh(item)
        assert item.regeneration_count == 1
        assert item.sent_for_review is True
        assert any("Butunlay yangi sarlavha" in text for text in session_calls.texts())

    async def test_regeneration_failure_is_reported(
        self, owner_id: int, dispatcher, bot, session_calls, session, owned_business, monkeypatch
    ):
        item = make_item(owned_business.id)
        session.add(item)
        await session.commit()

        async def boom(self, item_, *, instruction="", regenerate_image=False):
            raise RuntimeError("gemini down")

        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.regenerate", boom)

        await dispatcher.feed_update(
            bot, make_callback(owner_id, ReviewCB(action="regen", item_id=item.id).pack())
        )
        assert any("Xatolik" in text for text in session_calls.texts())


class TestBatchApproval:
    @pytest.fixture
    async def plan(self, session, owned_business) -> ContentPlan:
        plan = ContentPlan(
            business_id=owned_business.id,
            title="W40",
            year=2026,
            week_number=40,
            month_number=10,
            starts_on=utcnow().date(),
            ends_on=utcnow().date() + timedelta(days=6),
            status=ContentPlanStatus.PENDING_REVIEW,
            strategy={"theme": "Kuz intensivi"},
            notes="",
        )
        session.add(plan)
        await session.flush()
        for index in range(4):
            session.add(make_item(owned_business.id, content_plan_id=plan.id, headline=f"Post {index}"))
        await session.commit()
        return plan

    async def test_approve_all(self, owner_id: int, dispatcher, bot, session_calls, session, plan):
        plan_id = plan.id
        await dispatcher.feed_update(
            bot, make_callback(owner_id, BatchCB(action="approve_all", plan_id=plan_id).pack())
        )
        session.expire_all()   # the handler committed in its own session

        from app.repositories.content import ContentPlanRepository

        refreshed = await ContentPlanRepository(session).get_with_items(plan_id)
        assert refreshed.status == ContentPlanStatus.APPROVED
        assert all(item.status == ContentItemStatus.APPROVED for item in refreshed.items)
        assert "4 ta post tasdiqlandi" in (session_calls.last_of("EditMessageText").text or "")

    async def test_reject_all(self, owner_id: int, dispatcher, bot, session, plan):
        plan_id = plan.id
        await dispatcher.feed_update(
            bot, make_callback(owner_id, BatchCB(action="reject_all", plan_id=plan_id).pack())
        )
        session.expire_all()

        from app.repositories.content import ContentPlanRepository

        refreshed = await ContentPlanRepository(session).get_with_items(plan_id)
        assert all(item.status == ContentItemStatus.REJECTED for item in refreshed.items)

    async def test_show_lists_every_post(self, owner_id: int, dispatcher, bot, session_calls, plan):
        await dispatcher.feed_update(bot, make_callback(owner_id, BatchCB(action="show", plan_id=plan.id).pack()))
        listing = session_calls.texts()[-1]
        assert "Post 0" in listing and "Post 3" in listing


class TestReviewQueueCommand:
    async def test_review_sends_pending_items(
        self, owner_id: int, dispatcher, bot, session_calls, session, owned_business
    ):
        items = [make_item(owned_business.id, headline=f"Kutayotgan {i}") for i in range(2)]
        session.add_all(items)
        await session.commit()

        await dispatcher.feed_update(bot, make_update(owner_id, "/review"))

        texts = session_calls.texts()
        assert any("Kutayotgan 0" in text for text in texts)
        assert any("Kutayotgan 1" in text for text in texts)

        await session.refresh(items[0])
        assert items[0].sent_for_review is True
        assert items[0].review_chat_id == owner_id

    async def test_review_with_empty_queue(self, owner_id: int, dispatcher, bot, session_calls, owned_business):
        await dispatcher.feed_update(bot, make_update(owner_id, "/review"))
        assert "post yo'q" in session_calls.texts()[-1]


class TestStatusAndKnowledge:
    async def test_status_command(self, owner_id: int, dispatcher, bot, session_calls, owned_business):
        await dispatcher.feed_update(bot, make_update(owner_id, "/status"))
        text = session_calls.texts()[-1]
        assert owned_business.name in text
        assert "Bilim bazasi" in text

    async def test_kb_command_lists_missing_fields(self, owner_id: int, dispatcher, bot, session_calls, owned_business):
        await dispatcher.feed_update(bot, make_update(owner_id, "/kb"))
        text = session_calls.texts()[-1]
        assert "Yetishmayapti" in text

    async def test_pending_counts(self, owner_id: int, dispatcher, bot, session_calls, session, owned_business):
        session.add(make_item(owned_business.id))
        await session.commit()

        await dispatcher.feed_update(bot, make_update(owner_id, "/pending"))
        assert "Kontent holati" in session_calls.texts()[-1]


class TestFreeformKnowledge:
    async def test_plain_message_is_ingested_into_the_knowledge_base(
        self, owner_id: int, dispatcher, bot, session_calls, owned_business, monkeypatch
    ):
        from app.agents.onboarding import OnboardingResult
        from app.schemas.knowledge_base import KnowledgeExtraction

        async def fake_ingest(self, business, knowledge, message, source="telegram"):
            knowledge.phone = "+998901112233"
            return OnboardingResult(
                extraction=KnowledgeExtraction(),
                next_question=None,
                completeness=0.5,
                updated_fields=["phone"],
                summary="Telefon saqlandi",
            )

        monkeypatch.setattr("app.agents.onboarding.OnboardingAgent.ingest", fake_ingest)

        await dispatcher.feed_update(bot, make_update(owner_id, "Telefonimiz +998901112233"))
        assert "Telefon saqlandi" in session_calls.texts()[-1]

    async def test_menu_buttons_are_not_treated_as_knowledge(
        self, owner_id: int, dispatcher, bot, session_calls, owned_business
    ):
        await dispatcher.feed_update(bot, make_update(owner_id, "📊 Holat"))
        # Routed to /status, not to the knowledge ingester.
        assert owned_business.name in session_calls.texts()[-1]


class TestFootageShelf:
    """`/footage` stocks the library the person-on-screen families need."""

    @pytest.fixture
    def shelf_root(self, tmp_path, monkeypatch):
        """Point the media storage at a throwaway root for this test."""
        from app.services.storage import MediaStorage

        monkeypatch.setattr("app.services.storage._storage", MediaStorage(tmp_path))
        return tmp_path

    @pytest.fixture
    async def pro_business(self, session, owned_business) -> Business:
        owned_business.plan = Plan.PRO
        await session.commit()
        return owned_business

    @pytest.fixture
    def stub_download(self, monkeypatch):
        async def fake_download(bot: Bot, file_id: str) -> bytes:
            return b"fake-mp4-bytes"

        monkeypatch.setattr("app.bot.handlers.video._download", fake_download)

    async def test_command_opens_the_shelf(
        self, owner_id: int, dispatcher, bot, session_calls, shelf_root, pro_business
    ):
        await dispatcher.feed_update(bot, make_update(owner_id, "/footage"))
        assert "Video kadr javoni" in session_calls.texts()[-1]

    async def test_a_clip_is_stored_on_the_shelf(
        self, owner_id: int, dispatcher, bot, session_calls, shelf_root, pro_business, stub_download
    ):
        from app.services.brand_assets import own_footage

        await dispatcher.feed_update(bot, make_update(owner_id, "/footage"))
        await dispatcher.feed_update(bot, make_video_update(owner_id, update_id=2))

        clips = own_footage(pro_business.id)
        assert len(clips) == 1
        assert clips[0].suffix == ".mp4"
        assert clips[0].read_bytes() == b"fake-mp4-bytes"
        assert "javonga qo'shildi" in session_calls.texts()[-1]

    async def test_a_clip_outside_the_shelf_still_goes_to_the_editor(
        self, owner_id: int, dispatcher, bot, shelf_root, pro_business, stub_download, monkeypatch
    ):
        """No `/footage` first — the video is a post, not library material."""
        from app.services.brand_assets import own_footage

        queued: list[str] = []
        monkeypatch.setattr(
            "app.tasks.generation.edit_uploaded_video.delay",
            lambda *args, **kwargs: queued.append(args[0]),
        )

        await dispatcher.feed_update(bot, make_video_update(owner_id, update_id=3))

        assert queued == [str(pro_business.id)]
        assert own_footage(pro_business.id) == []

    async def test_text_while_the_shelf_is_open_is_not_ingested(
        self, owner_id: int, dispatcher, bot, session_calls, shelf_root, pro_business
    ):
        await dispatcher.feed_update(bot, make_update(owner_id, "/footage"))
        await dispatcher.feed_update(bot, make_update(owner_id, "narxlar 400 ming", update_id=4))

        assert "faqat video" in session_calls.texts()[-1]

    async def test_a_full_shelf_refuses_more(
        self, owner_id: int, dispatcher, bot, session_calls, shelf_root, pro_business,
        stub_download, monkeypatch,
    ):
        monkeypatch.setattr("app.bot.handlers.video.MAX_SHELF_CLIPS", 1)

        await dispatcher.feed_update(bot, make_update(owner_id, "/footage"))
        await dispatcher.feed_update(bot, make_video_update(owner_id, update_id=5))
        await dispatcher.feed_update(bot, make_video_update(owner_id, update_id=6))

        from app.services.brand_assets import own_footage

        assert len(own_footage(pro_business.id)) == 1
        assert "Javon to'ldi" in session_calls.texts()[-1]

    async def test_a_starter_plan_is_told_the_shelf_needs_pro(
        self, owner_id: int, dispatcher, bot, session_calls, shelf_root, owned_business
    ):
        await dispatcher.feed_update(bot, make_update(owner_id, "/footage"))
        assert "Pro" in session_calls.texts()[-1]


class TestEveryDecisionIsAttributable:
    """A rejection is a decision, and the system must be able to date it.

    Approving recorded who and when from the start; two of the three reject
    paths did not, so a month later the report could say five posts were
    rejected but not by whom or when. The asymmetry was an oversight — these
    pin it shut.
    """

    def _reject_paths(self) -> list[str]:
        import pathlib

        source = pathlib.Path("app/bot/handlers/review.py").read_text(encoding="utf-8")
        blocks = []
        for chunk in source.split("ContentItemStatus.REJECTED")[1:]:
            blocks.append(chunk[:400])
        return blocks

    def test_every_reject_path_stamps_the_time(self):
        for block in self._reject_paths():
            assert "reviewed_at" in block, block[:120]

    def test_every_reject_path_records_the_reviewer(self):
        for block in self._reject_paths():
            assert "reviewed_by" in block, block[:120]

    def test_there_is_more_than_one_reject_path(self):
        """Guards the test above: an empty list would pass vacuously."""
        assert len(self._reject_paths()) >= 3
