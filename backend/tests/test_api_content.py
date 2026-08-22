"""Plans, generation triggers and publish-now, end to end over HTTP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

pytestmark = pytest.mark.db


async def create_business(client, payload: dict) -> dict:
    response = await client.post("/api/v1/businesses", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def item_payload(business_id: str, **overrides) -> dict:
    payload = {
        "business_id": business_id,
        "content_type": "feed_post",
        "pillar": "sales",
        "platform": "telegram",
        "topic": "IELTS",
        "headline": "IELTS 7.0",
        "caption_tg": "Telegram matni",
        "caption_ig": "Instagram matni",
        "hashtags": ["#ielts"],
        "image_url": None,
        "scheduled_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "status": "pending_review",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def no_broker(monkeypatch):
    """Force the inline execution path used when Celery is unreachable."""
    monkeypatch.setattr("app.api.v1.generation._enqueue", lambda *a, **k: None)


class TestPlans:
    async def test_plan_detail_includes_items_and_counts(self, client, session, business_payload):
        from app.models.content_plan import ContentPlan
        from app.models.enums import ContentPlanStatus
        from app.utils.dates import utcnow

        business = await create_business(client, business_payload)

        plan = ContentPlan(
            business_id=business["id"],
            title="Test week",
            year=2026,
            week_number=34,
            month_number=8,
            starts_on=utcnow().date(),
            ends_on=utcnow().date() + timedelta(days=6),
            status=ContentPlanStatus.PENDING_REVIEW,
            strategy={"theme": "Avgust"},
            notes="",
        )
        session.add(plan)
        await session.commit()

        for pillar in ("sales", "educational"):
            await client.post(
                "/api/v1/items",
                json=item_payload(business["id"], pillar=pillar, content_plan_id=str(plan.id)),
            )

        response = await client.get(f"/api/v1/plans/{plan.id}")
        data = response.json()["data"]
        assert len(data["items"]) == 2
        assert data["pillar_counts"] == {"sales": 1, "educational": 1}
        assert data["strategy"]["theme"] == "Avgust"

    async def test_plan_listing_filters_by_business(self, client, session, business_payload):
        from app.models.content_plan import ContentPlan
        from app.models.enums import ContentPlanStatus
        from app.utils.dates import utcnow

        business = await create_business(client, business_payload)
        session.add(
            ContentPlan(
                business_id=business["id"], title="W35", year=2026, week_number=35, month_number=8,
                starts_on=utcnow().date(), ends_on=utcnow().date(),
                status=ContentPlanStatus.DRAFT, strategy={}, notes="",
            )
        )
        await session.commit()

        response = await client.get("/api/v1/plans", params={"business_id": business["id"]})
        assert response.json()["meta"]["total"] == 1

    async def test_approve_plan_approves_all_pending_items(self, client, session, business_payload):
        from app.models.content_plan import ContentPlan
        from app.models.enums import ContentPlanStatus
        from app.utils.dates import utcnow

        business = await create_business(client, business_payload)
        plan = ContentPlan(
            business_id=business["id"], title="W36", year=2026, week_number=36, month_number=9,
            starts_on=utcnow().date(), ends_on=utcnow().date(),
            status=ContentPlanStatus.PENDING_REVIEW, strategy={}, notes="",
        )
        session.add(plan)
        await session.commit()

        for _ in range(3):
            await client.post(
                "/api/v1/items", json=item_payload(business["id"], content_plan_id=str(plan.id))
            )

        response = await client.post(f"/api/v1/plans/{plan.id}/approve")
        assert response.json()["data"]["approved"] == 3

        detail = await client.get(f"/api/v1/plans/{plan.id}")
        assert detail.json()["data"]["status"] == "approved"
        assert all(item["status"] == "approved" for item in detail.json()["data"]["items"])

    async def test_missing_plan_is_404(self, client):
        response = await client.get("/api/v1/plans/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404


class TestGenerationTriggers:
    async def test_plan_generation_is_queued_when_a_broker_exists(
        self, client, business_payload, monkeypatch
    ):
        monkeypatch.setattr("app.api.v1.generation._enqueue", lambda *a, **k: "task-123")
        business = await create_business(client, business_payload)

        response = await client.post(
            "/api/v1/generate/plan", json={"business_id": business["id"], "posts_count": 6}
        )
        data = response.json()["data"]
        assert data["task_id"] == "task-123"
        assert data["status"] == "queued"

    async def test_generation_for_unknown_business_is_404(self, client, no_broker):
        response = await client.post(
            "/api/v1/generate/plan",
            json={"business_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert response.status_code == 404

    async def test_regenerate_rejects_published_items(self, client, business_payload, no_broker):
        business = await create_business(client, business_payload)
        created = await client.post(
            "/api/v1/items", json=item_payload(business["id"], status="published")
        )
        item_id = created.json()["data"]["id"]

        response = await client.post(
            f"/api/v1/generate/item/{item_id}/regenerate", json={"instruction": "boshqacha yoz"}
        )
        assert response.status_code == 409

    async def test_publish_now_runs_inline_and_marks_published(
        self, client, session, business_payload, no_broker, monkeypatch
    ):
        from app.services.telegram_publisher import TelegramResult

        class FakePublisher:
            def __init__(self, token: str) -> None:
                self.token = token

            async def send_message(self, chat_id, text, **kwargs):
                return TelegramResult(message_id="55", chat_id=str(chat_id), raw={})

        monkeypatch.setattr("app.services.telegram_publisher.TelegramPublisher", FakePublisher)

        business = await create_business(client, business_payload)
        await client.put(
            f"/api/v1/businesses/{business['id']}/credentials",
            json={"tg_bot_token": "123:ABC", "tg_channel_id": "@chan", "telegram_enabled": True},
        )
        created = await client.post(
            "/api/v1/items", json=item_payload(business["id"], status="approved")
        )
        item_id = created.json()["data"]["id"]

        response = await client.post(f"/api/v1/generate/item/{item_id}/publish", json={"force": False})
        assert response.status_code == 200

        detail = await client.get(f"/api/v1/items/{item_id}")
        assert detail.json()["data"]["status"] == "published"
        assert detail.json()["data"]["tg_message_id"] == "55"

        logs = await client.get(f"/api/v1/items/{item_id}/logs")
        assert logs.json()["data"][0]["state"] == "success"

    async def test_publish_now_conflicts_on_already_published(self, client, business_payload, no_broker):
        business = await create_business(client, business_payload)
        created = await client.post(
            "/api/v1/items", json=item_payload(business["id"], status="published")
        )
        item_id = created.json()["data"]["id"]

        response = await client.post(f"/api/v1/generate/item/{item_id}/publish", json={"force": False})
        assert response.status_code == 409


class TestCredentialsVerification:
    async def test_verify_reports_live_bot_details(self, client, business_payload, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            method = str(request.url).rsplit("/", 1)[-1]
            if method == "getMe":
                return httpx.Response(200, json={"ok": True, "result": {"username": "autosmm_bot"}})
            return httpx.Response(200, json={"ok": True, "result": {"title": "Bright Channel"}})

        mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        async def fake_get_client(name="default", *, timeout=None):
            return mock

        monkeypatch.setattr("app.services.telegram_publisher.get_client", fake_get_client)

        business = await create_business(client, business_payload)
        await client.put(
            f"/api/v1/businesses/{business['id']}/credentials",
            json={"tg_bot_token": "123:ABC", "tg_channel_id": "@chan", "telegram_enabled": True},
        )

        response = await client.post(f"/api/v1/businesses/{business['id']}/credentials/verify")
        telegram = response.json()["data"]["telegram"]
        assert telegram["ok"] is True
        assert telegram["bot"] == "autosmm_bot"
        assert telegram["channel"] == "Bright Channel"

    async def test_verify_reports_unconfigured_channels(self, client, business_payload):
        business = await create_business(client, business_payload)
        response = await client.post(f"/api/v1/businesses/{business['id']}/credentials/verify")
        data = response.json()["data"]
        assert data["telegram"]["configured"] is False
        assert data["instagram"]["configured"] is False

    async def test_refresh_token_requires_a_stored_token(self, client, business_payload):
        business = await create_business(client, business_payload)
        response = await client.post(f"/api/v1/businesses/{business['id']}/credentials/refresh-token")
        assert response.status_code == 400


class TestAuth:
    async def test_production_mode_requires_the_api_key(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "env", "production", raising=False)
        response = await client.get("/api/v1/businesses", headers={"X-API-Key": "wrong"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    async def test_correct_key_passes(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "env", "production", raising=False)
        response = await client.get("/api/v1/businesses")
        assert response.status_code == 200
