"""Publishing service behaviour with stubbed channel APIs."""

from __future__ import annotations

from datetime import timedelta
from typing import ClassVar

import pytest

from app.models.business import Business, BusinessCredentials
from app.models.content_item import ContentItem
from app.models.enums import (
    BusinessCategory,
    ContentItemStatus,
    ContentType,
    Language,
    Platform,
    PublishState,
    ToneOfVoice,
)
from app.services.publisher import PublishingService
from app.utils.dates import utcnow

pytestmark = pytest.mark.db


def make_item(business_id, **overrides) -> ContentItem:
    item = ContentItem(
        business_id=business_id,
        content_type=ContentType.FEED_POST,
        platform=Platform.BOTH,
        topic="IELTS",
        headline="IELTS 7.0",
        caption_tg="Telegram matni",
        caption_ig="Instagram matni",
        hashtags=["#ielts"],
        image_url="https://cdn.example.com/a.png",
        scheduled_at=utcnow() - timedelta(minutes=5),
        status=ContentItemStatus.APPROVED,
        carousel_slides=[],
        options={},
        script={},
        editor_report={},
        ai_meta={},
        retry_count=0,
        regeneration_count=0,
        quality_score=8.0,
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


@pytest.fixture
async def business(session) -> Business:
    business = Business(
        name="Publish Test",
        slug=f"publish-{utcnow().timestamp()}",
        category=BusinessCategory.EDUCATION,
        tone_of_voice=ToneOfVoice.CASUAL,
        target_audience="",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={},
    )
    session.add(business)
    await session.flush()
    credentials = BusinessCredentials(
        business_id=business.id,
        tg_bot_token="123:ABC",
        tg_channel_id="@test_channel",
        telegram_enabled=True,
        instagram_enabled=False,
    )
    session.add(credentials)
    await session.flush()
    business.credentials = credentials
    return business


class FakeTelegram:
    """Records the call instead of hitting the Bot API."""

    calls: ClassVar[list[tuple[str, tuple, dict]]] = []

    def __init__(self, token: str) -> None:
        self.token = token

    async def _record(self, name: str, *args, **kwargs):
        from app.services.telegram_publisher import TelegramResult

        FakeTelegram.calls.append((name, args, kwargs))
        return TelegramResult(message_id="4242", chat_id=str(args[0]), raw={})

    async def send_message(self, *args, **kwargs):
        return await self._record("send_message", *args, **kwargs)

    async def send_photo(self, *args, **kwargs):
        return await self._record("send_photo", *args, **kwargs)

    async def send_album(self, *args, **kwargs):
        return await self._record("send_album", *args, **kwargs)

    async def send_quiz(self, *args, **kwargs):
        return await self._record("send_quiz", *args, **kwargs)


@pytest.fixture(autouse=True)
def stub_telegram(monkeypatch):
    FakeTelegram.calls = []
    monkeypatch.setattr("app.services.telegram_publisher.TelegramPublisher", FakeTelegram)
    return FakeTelegram


class TestTelegramRouting:
    async def test_photo_post(self, session, business):
        item = make_item(business.id)
        session.add(item)
        await session.flush()

        result = await PublishingService(session).publish(item, business)

        assert item.status == ContentItemStatus.PUBLISHED
        assert item.tg_state == PublishState.SUCCESS
        assert item.tg_message_id == "4242"
        assert item.published_at is not None
        assert FakeTelegram.calls[0][0] == "send_photo"
        assert result.any_success

    async def test_text_only_post_uses_send_message(self, session, business):
        item = make_item(business.id, image_url=None)
        session.add(item)
        await session.flush()

        await PublishingService(session).publish(item, business)
        assert FakeTelegram.calls[0][0] == "send_message"

    async def test_carousel_uses_album(self, session, business):
        item = make_item(
            business.id,
            content_type=ContentType.CAROUSEL,
            carousel_slides=[
                {"index": 1, "image_url": "https://cdn/1.png"},
                {"index": 2, "image_url": "https://cdn/2.png"},
            ],
        )
        session.add(item)
        await session.flush()

        await PublishingService(session).publish(item, business)
        assert FakeTelegram.calls[0][0] == "send_album"
        assert len(FakeTelegram.calls[0][1][1]) == 2

    async def test_quiz_sends_poll(self, session, business):
        item = make_item(
            business.id,
            content_type=ContentType.TELEGRAM_QUIZ,
            platform=Platform.TELEGRAM,
            image_url=None,
            options={"question": "IELTS max?", "answers": ["9.0", "8.0"], "correct_option_id": 0},
        )
        session.add(item)
        await session.flush()

        await PublishingService(session).publish(item, business)
        methods = [call[0] for call in FakeTelegram.calls]
        assert "send_quiz" in methods

    async def test_reels_script_is_sent_as_text(self, session, business):
        item = make_item(
            business.id,
            content_type=ContentType.REELS_SCRIPT,
            platform=Platform.TELEGRAM,
            script={"duration_sec": 30, "scenes": [{"t": "0-3s", "shot": "hook", "on_screen": "IELTS"}]},
        )
        session.add(item)
        await session.flush()

        await PublishingService(session).publish(item, business)
        assert FakeTelegram.calls[0][0] == "send_message"
        assert "REELS" in FakeTelegram.calls[0][1][1]


class TestFailureHandling:
    async def test_failure_marks_item_and_counts_retry(self, session, business, monkeypatch):
        from app.core.exceptions import PublishError

        class Failing(FakeTelegram):
            async def send_photo(self, *args, **kwargs):
                raise PublishError("telegram", "chat not found", retryable=False)

        monkeypatch.setattr("app.services.telegram_publisher.TelegramPublisher", Failing)

        item = make_item(business.id)
        session.add(item)
        await session.flush()

        await PublishingService(session).publish(item, business)

        assert item.status == ContentItemStatus.FAILED
        assert item.retry_count == 1
        assert "chat not found" in (item.last_error or "")

    async def test_instagram_skipped_when_not_configured(self, session, business):
        item = make_item(business.id, platform=Platform.BOTH)
        session.add(item)
        await session.flush()

        result = await PublishingService(session).publish(item, business)
        states = {o.platform: o.state for o in result.outcomes}
        assert states[Platform.INSTAGRAM] == PublishState.SKIPPED
        assert item.status == ContentItemStatus.PUBLISHED

    async def test_no_channel_configured_fails_without_retrying(self, session, business):
        from app.core.config import settings

        business.credentials.telegram_enabled = False
        await session.flush()

        item = make_item(business.id)
        session.add(item)
        await session.flush()

        result = await PublishingService(session).publish(item, business)

        assert result.all_skipped
        assert item.status == ContentItemStatus.FAILED
        assert "no channel configured" in (item.last_error or "")
        # Retries are exhausted up front so `retry_failed` never re-queues it.
        assert item.retry_count >= settings.max_publish_retries

    async def test_already_published_is_not_reposted(self, session, business):
        item = make_item(business.id, status=ContentItemStatus.PUBLISHED)
        session.add(item)
        await session.flush()

        await PublishingService(session).publish(item, business)
        assert FakeTelegram.calls == []

    async def test_publish_log_is_written(self, session, business):
        from app.repositories.content import PublishLogRepository

        item = make_item(business.id)
        session.add(item)
        await session.flush()

        await PublishingService(session).publish(item, business)
        logs = await PublishLogRepository(session).for_item(item.id)
        assert any(entry.state == PublishState.SUCCESS for entry in logs)


class TestDueQuery:
    async def test_only_approved_and_due_items_are_returned(self, session, business):
        from app.repositories.content import ContentItemRepository

        due = make_item(business.id)
        future = make_item(business.id, scheduled_at=utcnow() + timedelta(days=1))
        pending = make_item(business.id, status=ContentItemStatus.PENDING_REVIEW)
        session.add_all([due, future, pending])
        await session.flush()

        rows = await ContentItemRepository(session).due_for_publishing(limit=50)
        ids = {row.id for row in rows}
        assert due.id in ids
        assert future.id not in ids
        assert pending.id not in ids
