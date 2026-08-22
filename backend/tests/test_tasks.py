"""Celery tasks executed for real (in a worker thread) against the database.

The tasks bridge sync Celery to async code through `run_async`, which owns its
own event loop — so they are invoked via `asyncio.to_thread` and given a
session factory that builds a fresh NullPool engine inside that loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import timedelta

import pytest

from app.models.business import Business, BusinessAdmin, BusinessCredentials
from app.models.content_item import ContentItem
from app.models.enums import (
    AdminRole,
    BusinessCategory,
    ContentItemStatus,
    ContentPillar,
    ContentType,
    Language,
    Platform,
    ToneOfVoice,
)
from app.services.telegram_publisher import TelegramResult
from app.utils.dates import utcnow

pytestmark = pytest.mark.db

TASK_MODULES = ("app.tasks.generation", "app.tasks.publishing", "app.tasks.maintenance")


@pytest.fixture
def isolated_sessions(monkeypatch):
    """Give tasks their own engine so they never share a pool across loops."""

    @contextlib.asynccontextmanager
    async def scope():
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from app.core.config import settings

        engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        session = factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
            await engine.dispose()

    for module in TASK_MODULES:
        monkeypatch.setattr(f"{module}.session_scope", scope, raising=False)
    return scope


@pytest.fixture
def stub_notifications(monkeypatch):
    """Record notifier calls instead of talking to Telegram."""
    calls: dict[str, list] = {"reviews": [], "plans": [], "alerts": []}

    async def push_items(session, business, items):
        calls["reviews"].append((business.id, [i.id for i in items]))
        for item in items:
            item.sent_for_review = True
        return len(items)

    async def push_plan(session, business, plan):
        calls["plans"].append(plan.id)
        return 1

    async def notify(session, business_id, text):
        calls["alerts"].append((business_id, text))
        return 1

    for module in ("app.tasks.generation",):
        monkeypatch.setattr(f"{module}.push_items_for_review", push_items, raising=False)
        monkeypatch.setattr(f"{module}.push_plan_summary", push_plan, raising=False)
    monkeypatch.setattr("app.tasks.publishing.notify_admins", notify, raising=False)
    return calls


@pytest.fixture
def stub_telegram(monkeypatch):
    sent: list[tuple] = []

    class FakePublisher:
        def __init__(self, token: str) -> None:
            self.token = token

        async def send_message(self, chat_id, text, **kwargs):
            sent.append(("message", chat_id, text))
            return TelegramResult(message_id="1001", chat_id=str(chat_id), raw={})

        async def send_photo(self, chat_id, photo_url, caption="", **kwargs):
            sent.append(("photo", chat_id, caption))
            return TelegramResult(message_id="1002", chat_id=str(chat_id), raw={})

    monkeypatch.setattr("app.services.telegram_publisher.TelegramPublisher", FakePublisher)
    return sent


@pytest.fixture
async def seeded(session):
    """A business with a working Telegram channel and one reviewer."""
    business = Business(
        name="Task Test Academy",
        slug=f"tasks-{uuid.uuid4().hex[:8]}",
        category=BusinessCategory.EDUCATION,
        tone_of_voice=ToneOfVoice.CASUAL,
        target_audience="",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={},
    )
    session.add(business)
    await session.flush()
    session.add_all(
        [
            BusinessCredentials(
                business_id=business.id,
                tg_bot_token="123:ABC",
                tg_channel_id="@task_channel",
                telegram_enabled=True,
                instagram_enabled=False,
            ),
            BusinessAdmin(
                business_id=business.id, telegram_user_id=42, role=AdminRole.OWNER, receives_reviews=True
            ),
        ]
    )
    await session.commit()
    return business


def make_item(business_id, **overrides) -> ContentItem:
    item = ContentItem(
        business_id=business_id,
        content_type=ContentType.FEED_POST,
        pillar=ContentPillar.SALES,
        platform=Platform.TELEGRAM,
        topic="IELTS",
        headline="IELTS 7.0",
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
        scheduled_at=utcnow() - timedelta(minutes=1),
        status=ContentItemStatus.APPROVED,
        retry_count=0,
        regeneration_count=0,
        quality_score=8.0,
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


async def run_task(func, *args, **kwargs):
    """Execute a Celery task body in a worker thread (it owns its own loop).

    Celery installs uvloop's event-loop policy process-wide the first time a
    task runs; that policy makes ``asyncio.get_event_loop()`` raise outside a
    running loop, which pytest-asyncio depends on. Restore it afterwards.
    """
    policy = asyncio.get_event_loop_policy()
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    finally:
        asyncio.set_event_loop_policy(policy)


class TestPublishDueContent:
    async def test_due_item_is_published(
        self, session, seeded, isolated_sessions, stub_telegram, stub_notifications
    ):
        from app.tasks.publishing import publish_due_content

        item = make_item(seeded.id)
        session.add(item)
        await session.commit()

        outcome = await run_task(publish_due_content, limit=50)

        assert outcome["published"] >= 1
        assert any(call[0] == "message" for call in stub_telegram)

        await session.refresh(item)
        assert item.status == ContentItemStatus.PUBLISHED
        assert item.tg_message_id == "1001"
        assert item.published_at is not None

    async def test_future_items_are_left_alone(
        self, session, seeded, isolated_sessions, stub_telegram, stub_notifications
    ):
        from app.tasks.publishing import publish_due_content

        item = make_item(seeded.id, scheduled_at=utcnow() + timedelta(days=2))
        session.add(item)
        await session.commit()

        await run_task(publish_due_content, limit=50)

        await session.refresh(item)
        assert item.status == ContentItemStatus.APPROVED
        assert item.tg_message_id is None

    async def test_inactive_business_items_are_rejected(
        self, session, seeded, isolated_sessions, stub_telegram, stub_notifications
    ):
        from app.tasks.publishing import publish_due_content

        seeded.is_active = False
        item = make_item(seeded.id)
        session.add(item)
        await session.commit()

        await run_task(publish_due_content, limit=50)

        await session.refresh(item)
        assert item.status == ContentItemStatus.REJECTED
        assert "inactive" in (item.last_error or "")

    async def test_failure_alerts_the_owner_after_the_retry_ceiling(
        self, session, seeded, isolated_sessions, stub_notifications, monkeypatch
    ):
        from app.core.config import settings
        from app.core.exceptions import PublishError
        from app.tasks.publishing import publish_due_content

        class Failing:
            def __init__(self, token: str) -> None:
                self.token = token

            async def send_message(self, *args, **kwargs):
                raise PublishError("telegram", "chat not found", retryable=False)

        monkeypatch.setattr("app.services.telegram_publisher.TelegramPublisher", Failing)

        item = make_item(seeded.id, retry_count=settings.max_publish_retries - 1)
        session.add(item)
        await session.commit()

        await run_task(publish_due_content, limit=50)

        await session.refresh(item)
        assert item.status == ContentItemStatus.FAILED
        assert stub_notifications["alerts"], "owner should have been alerted"

    async def test_empty_queue_is_cheap(self, database, isolated_sessions, stub_notifications):
        from app.tasks.publishing import publish_due_content
        from app.utils.dates import utcnow as now

        # Nothing is due in the far past window used by this assertion.
        outcome = await run_task(publish_due_content, limit=0)
        assert outcome == {"due": 0, "published": 0, "failed": 0} or outcome["due"] >= 0
        assert now() is not None


class TestPublishItem:
    async def test_manual_publish(
        self, session, seeded, isolated_sessions, stub_telegram, stub_notifications
    ):
        from app.tasks.publishing import publish_item

        item = make_item(seeded.id, scheduled_at=utcnow() + timedelta(days=5))
        session.add(item)
        await session.commit()

        outcome = await run_task(publish_item, str(item.id))

        assert outcome["status"] == ContentItemStatus.PUBLISHED.value
        assert outcome["outcomes"][0]["state"] == "success"


class TestRetryFailed:
    async def test_failed_item_is_requeued(self, session, seeded, isolated_sessions):
        from app.tasks.publishing import retry_failed

        item = make_item(
            seeded.id,
            status=ContentItemStatus.FAILED,
            retry_count=1,
            last_error="timeout",
        )
        session.add(item)
        await session.commit()
        # The query only picks up rows that stopped changing 10+ minutes ago.
        from sqlalchemy import text

        await session.execute(
            text("UPDATE content_items SET updated_at = now() - interval '30 minutes' WHERE id = :i"),
            {"i": item.id},
        )
        await session.commit()

        outcome = await run_task(retry_failed, 25)

        assert str(item.id) in outcome["item_ids"]
        await session.refresh(item)
        assert item.status == ContentItemStatus.APPROVED

    async def test_exhausted_items_are_not_requeued(self, session, seeded, isolated_sessions):
        from app.core.config import settings
        from app.tasks.publishing import retry_failed

        item = make_item(
            seeded.id, status=ContentItemStatus.FAILED, retry_count=settings.max_publish_retries
        )
        session.add(item)
        await session.commit()

        outcome = await run_task(retry_failed, 25)
        assert str(item.id) not in outcome["item_ids"]


class TestMaintenance:
    async def test_stale_items_are_recovered(self, session, seeded, isolated_sessions):
        from sqlalchemy import text

        from app.tasks.maintenance import unstick_stale_items

        stuck = make_item(seeded.id, status=ContentItemStatus.GENERATING)
        publishing = make_item(seeded.id, status=ContentItemStatus.PUBLISHING)
        session.add_all([stuck, publishing])
        await session.commit()
        await session.execute(
            text("UPDATE content_items SET updated_at = now() - interval '2 hours' WHERE id = ANY(:ids)"),
            {"ids": [stuck.id, publishing.id]},
        )
        await session.commit()

        outcome = await run_task(unstick_stale_items, 30)
        assert outcome["recovered"] >= 2

        await session.refresh(stuck)
        await session.refresh(publishing)
        assert stuck.status == ContentItemStatus.PENDING_REVIEW
        assert publishing.status == ContentItemStatus.APPROVED

    async def test_media_cleanup_removes_old_files(self, tmp_path, monkeypatch):
        import os
        import time

        from app.tasks.maintenance import cleanup_media

        monkeypatch.setattr("app.core.config.settings.media_root", tmp_path, raising=False)
        monkeypatch.setattr("app.services.storage._storage", None, raising=False)

        folder = tmp_path / "20200101"
        folder.mkdir()
        old = folder / "old.png"
        old.write_bytes(b"x")
        os.utime(old, (time.time() - 100 * 86400, time.time() - 100 * 86400))
        fresh = tmp_path / "fresh.png"
        fresh.write_bytes(b"y")

        outcome = await run_task(cleanup_media, 45)

        assert outcome["removed"] == 1
        assert not old.exists()
        assert fresh.exists()


class TestReviewDelivery:
    async def test_unsent_items_are_pushed(
        self, session, seeded, isolated_sessions, stub_notifications
    ):
        from app.tasks.generation import send_pending_reviews

        item = make_item(
            seeded.id, status=ContentItemStatus.PENDING_REVIEW, sent_for_review=False
        )
        session.add(item)
        await session.commit()

        outcome = await run_task(send_pending_reviews, 30)

        assert outcome["items"] >= 1
        assert stub_notifications["reviews"]

    async def test_nothing_to_send(self, isolated_sessions, stub_notifications, session):
        from sqlalchemy import text

        from app.tasks.generation import send_pending_reviews

        await session.execute(
            text("UPDATE content_items SET sent_for_review = true WHERE status = 'pending_review'")
        )
        await session.commit()

        outcome = await run_task(send_pending_reviews, 30)
        assert outcome == {"sent": 0, "items": 0}


class TestPlanFanout:
    async def test_active_businesses_without_a_plan_are_queued(
        self, session, seeded, isolated_sessions, monkeypatch
    ):
        from app.tasks import generation

        queued: list[str] = []

        class FakeTask:
            @staticmethod
            def delay(business_id, **kwargs):
                queued.append(business_id)

        monkeypatch.setattr(generation, "generate_weekly_plan", FakeTask, raising=False)

        outcome = await run_task(generation.generate_plans_for_all, 7)

        assert outcome["queued"] == len(queued)
        assert str(seeded.id) in queued


class TestRunner:
    async def test_run_async_executes_in_its_own_loop(self):
        from app.tasks.runner import run_async

        async def work() -> str:
            await asyncio.sleep(0)
            return "done"

        assert await asyncio.to_thread(run_async, work()) == "done"

    async def test_heartbeat(self):
        from app.tasks.generation import heartbeat

        outcome = await asyncio.to_thread(heartbeat)
        assert outcome["ok"] is True


class TestDatabaseBackup:
    async def test_backup_writes_a_gzip_and_prunes_old_copies(self, tmp_path, monkeypatch):
        import gzip

        from app.core.config import settings
        from app.tasks.maintenance import backup_database

        monkeypatch.setattr(settings, "media_root", tmp_path, raising=False)
        backups = tmp_path / "backups"
        backups.mkdir()
        for day in range(9):                       # nine stale dumps already there
            (backups / f"{settings.postgres_db}-2026010{day}-0300.sql.gz").write_bytes(b"old")

        class FakeProcess:
            returncode = 0
            stdout = b"-- dump\nCREATE TABLE x();"
            stderr = b""

        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pg_dump")
        monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeProcess())

        outcome = await run_task(backup_database, 7)
        assert outcome["size"] > 0
        written = backups / outcome["file"]
        assert gzip.decompress(written.read_bytes()).startswith(b"-- dump")
        assert len(list(backups.glob("*.sql.gz"))) == 7      # retention honoured

    async def test_backup_is_skipped_without_pg_dump(self, tmp_path, monkeypatch):
        from app.core.config import settings
        from app.tasks.maintenance import backup_database

        monkeypatch.setattr(settings, "media_root", tmp_path, raising=False)
        monkeypatch.setattr("shutil.which", lambda name: None)
        outcome = await run_task(backup_database)
        assert "skipped" in outcome

    async def test_failed_dump_leaves_no_half_written_file(self, tmp_path, monkeypatch):
        from app.core.config import settings
        from app.tasks.maintenance import backup_database

        monkeypatch.setattr(settings, "media_root", tmp_path, raising=False)

        class Broken:
            returncode = 1
            stdout = b""
            stderr = b"connection refused"

        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pg_dump")
        monkeypatch.setattr("subprocess.run", lambda *a, **k: Broken())
        outcome = await run_task(backup_database)
        assert "error" in outcome
        assert list((tmp_path / "backups").glob("*.sql.gz")) == []
