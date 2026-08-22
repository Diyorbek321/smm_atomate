"""End-to-end API tests against a real PostgreSQL database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.db


async def create_business(client, payload: dict) -> dict:
    response = await client.post("/api/v1/businesses", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["success"] is True
    return body["data"]


class TestHealth:
    async def test_health_is_public(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_readiness_reports_database(self, client):
        response = await client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["database"] is True

    async def test_root(self, client):
        assert (await client.get("/")).json()["docs"] == "/docs"


class TestBusinessCrud:
    async def test_create_and_fetch(self, client, business_payload):
        business = await create_business(client, business_payload)
        assert business["name"] == business_payload["name"]
        assert business["slug"]
        assert business["is_active"] is True

        detail = await client.get(f"/api/v1/businesses/{business['id']}")
        assert detail.status_code == 200
        assert detail.json()["data"]["id"] == business["id"]

    async def test_knowledge_base_is_created_with_business(self, client, business_payload):
        business = await create_business(client, business_payload)
        response = await client.get(f"/api/v1/businesses/{business['id']}/knowledge")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["business_id"] == business["id"]
        assert data["completeness_score"] == 0.0

    async def test_patch_updates_only_given_fields(self, client, business_payload):
        business = await create_business(client, business_payload)
        response = await client.patch(
            f"/api/v1/businesses/{business['id']}", json={"tone_of_voice": "bold"}
        )
        data = response.json()["data"]
        assert data["tone_of_voice"] == "bold"
        assert data["name"] == business["name"]

    async def test_list_is_paginated(self, client, business_payload):
        await create_business(client, business_payload)
        response = await client.get("/api/v1/businesses", params={"page": 1, "limit": 1})
        body = response.json()
        assert len(body["data"]) <= 1
        assert body["meta"]["total"] >= 1

    async def test_missing_business_returns_envelope_404(self, client):
        response = await client.get("/api/v1/businesses/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "not_found"

    async def test_invalid_timezone_rejected(self, client, business_payload):
        response = await client.post(
            "/api/v1/businesses", json={**business_payload, "timezone": "Mars/Olympus"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_delete(self, client, business_payload):
        business = await create_business(client, business_payload)
        assert (await client.delete(f"/api/v1/businesses/{business['id']}")).status_code == 200
        assert (await client.get(f"/api/v1/businesses/{business['id']}")).status_code == 404


class TestCredentials:
    async def test_secrets_are_masked_on_read(self, client, business_payload):
        business = await create_business(client, business_payload)
        await client.put(
            f"/api/v1/businesses/{business['id']}/credentials",
            json={
                "tg_bot_token": "123456:AAHsecretvalue1234",
                "tg_channel_id": "@my_channel",
                "telegram_enabled": True,
            },
        )
        response = await client.get(f"/api/v1/businesses/{business['id']}/credentials")
        data = response.json()["data"]
        assert data["tg_bot_token"].startswith("****")
        assert "AAHsecret" not in data["tg_bot_token"]
        assert data["telegram_ready"] is True

    async def test_token_round_trips_through_encryption(self, client, session, business_payload):
        from sqlalchemy import select

        from app.models.business import BusinessCredentials

        business = await create_business(client, business_payload)
        await client.put(
            f"/api/v1/businesses/{business['id']}/credentials",
            json={"tg_bot_token": "secret-token-value", "tg_channel_id": "@c"},
        )
        row = (
            await session.execute(
                select(BusinessCredentials).where(BusinessCredentials.business_id == business["id"])
            )
        ).scalars().one()
        # The ORM decrypts transparently…
        assert row.tg_bot_token == "secret-token-value"

    async def test_raw_column_is_ciphertext(self, client, session, business_payload):
        from sqlalchemy import text

        business = await create_business(client, business_payload)
        await client.put(
            f"/api/v1/businesses/{business['id']}/credentials",
            json={"tg_bot_token": "secret-token-value", "tg_channel_id": "@c"},
        )
        raw = (
            await session.execute(
                text("SELECT tg_bot_token FROM business_credentials WHERE business_id = :bid"),
                {"bid": business["id"]},
            )
        ).scalar()
        assert raw is not None
        assert raw.startswith("enc::v1::")
        assert "secret-token-value" not in raw


class TestKnowledgeBase:
    async def test_update_and_completeness(self, client, business_payload):
        business = await create_business(client, business_payload)
        response = await client.put(
            f"/api/v1/businesses/{business['id']}/knowledge",
            json={
                "key_offerings": [{"name": "IELTS intensiv", "duration": "3 oy"}],
                "prices": [{"item": "IELTS intensiv", "price": 600000, "currency": "UZS"}],
                "usps": ["Kafolatli natija"],
                "phone": "+998901234567",
                "faq": [{"q": "Qachon?", "a": "18:00"}],
                "teacher_profiles": [{"name": "Aziz", "role": "IELTS"}],
                "raw_notes": "Markaz 2019 yildan beri ishlaydi va 500 dan ortiq bitiruvchisi bor.",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["completeness_score"] == 1.0
        assert data["version"] == 2

    async def test_ingest_requires_text(self, client, business_payload):
        business = await create_business(client, business_payload)
        response = await client.post(f"/api/v1/businesses/{business['id']}/knowledge/ingest", json={})
        assert response.status_code == 400


class TestAdmins:
    async def test_add_and_list(self, client, business_payload):
        business = await create_business(client, business_payload)
        response = await client.post(
            f"/api/v1/businesses/{business['id']}/admins",
            json={"telegram_user_id": 123456, "full_name": "Owner", "role": "owner"},
        )
        assert response.status_code == 201

        listing = await client.get(f"/api/v1/businesses/{business['id']}/admins")
        assert len(listing.json()["data"]) == 1

    async def test_upsert_is_idempotent(self, client, business_payload):
        business = await create_business(client, business_payload)
        for _ in range(2):
            await client.post(
                f"/api/v1/businesses/{business['id']}/admins",
                json={"telegram_user_id": 999, "role": "manager"},
            )
        listing = await client.get(f"/api/v1/businesses/{business['id']}/admins")
        assert len(listing.json()["data"]) == 1


class TestContentItems:
    async def _item_payload(self, business_id: str) -> dict:
        return {
            "business_id": business_id,
            "content_type": "feed_post",
            "pillar": "sales",
            "platform": "both",
            "topic": "IELTS intensiv",
            "headline": "IELTS 7.0",
            "caption_tg": "Test caption",
            "caption_ig": "Test caption",
            "hashtags": ["#ielts"],
            "scheduled_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "status": "pending_review",
        }

    async def test_create_list_approve(self, client, business_payload):
        business = await create_business(client, business_payload)
        created = await client.post("/api/v1/items", json=await self._item_payload(business["id"]))
        assert created.status_code == 201
        item = created.json()["data"]

        listing = await client.get("/api/v1/items", params={"business_id": business["id"]})
        assert listing.json()["meta"]["total"] == 1

        approved = await client.post(f"/api/v1/items/{item['id']}/approve")
        assert approved.json()["data"]["status"] == "approved"

    async def test_filter_by_status(self, client, business_payload):
        business = await create_business(client, business_payload)
        await client.post("/api/v1/items", json=await self._item_payload(business["id"]))
        response = await client.get(
            "/api/v1/items", params={"business_id": business["id"], "status": "approved"}
        )
        assert response.json()["meta"]["total"] == 0

    async def test_bulk_status(self, client, business_payload):
        business = await create_business(client, business_payload)
        ids = []
        for _ in range(3):
            created = await client.post("/api/v1/items", json=await self._item_payload(business["id"]))
            ids.append(created.json()["data"]["id"])

        response = await client.post(
            "/api/v1/items/bulk-status", json={"item_ids": ids, "status": "approved"}
        )
        assert response.json()["data"]["updated"] == 3

    async def test_bulk_status_rejects_published(self, client):
        response = await client.post(
            "/api/v1/items/bulk-status", json={"item_ids": [], "status": "published"}
        )
        assert response.status_code == 422

    async def test_published_item_cannot_be_edited(self, client, business_payload):
        business = await create_business(client, business_payload)
        payload = await self._item_payload(business["id"])
        payload["status"] = "published"
        created = await client.post("/api/v1/items", json=payload)
        item_id = created.json()["data"]["id"]

        response = await client.patch(f"/api/v1/items/{item_id}", json={"headline": "x"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "conflict"


class TestPrompts:
    async def test_defaults_are_exposed(self, client):
        response = await client.get("/api/v1/prompts/defaults/copywriter")
        assert "SMM" in response.json()["data"]["system_prompt"]

    async def test_versioning_on_update(self, client):
        created = await client.post(
            "/api/v1/prompts",
            json={"name": f"tone-{datetime.now().timestamp()}", "agent": "copywriter",
                  "system_prompt": "Birinchi versiya matni"},
        )
        prompt = created.json()["data"]
        assert prompt["version"] == 1

        updated = await client.patch(
            f"/api/v1/prompts/{prompt['id']}", json={"system_prompt": "Ikkinchi versiya matni"}
        )
        data = updated.json()["data"]
        assert data["version"] == 2
        assert data["versions"][0]["system_prompt"] == "Birinchi versiya matni"

        rolled = await client.post(f"/api/v1/prompts/{prompt['id']}/rollback/1")
        assert rolled.json()["data"]["system_prompt"] == "Birinchi versiya matni"


class TestAnalytics:
    async def test_summary_shape(self, client, business_payload):
        await create_business(client, business_payload)
        response = await client.get("/api/v1/analytics/summary")
        data = response.json()["data"]
        assert data["total_businesses"] >= 1
        assert "pillar_distribution" in data
        assert isinstance(data["upcoming"], list)

    async def test_business_analytics(self, client, business_payload):
        business = await create_business(client, business_payload)
        response = await client.get(f"/api/v1/analytics/business/{business['id']}")
        data = response.json()["data"]
        assert data["business_id"] == business["id"]
        assert data["items_total"] == 0


class TestProviders:
    async def test_provider_status(self, client):
        data = (await client.get("/api/v1/system/providers")).json()["data"]
        assert "gemini" in data and "images" in data


class TestPlanApi:
    """Tier selection at creation time, and filtering the list by it."""

    async def test_default_tier_is_start(self, client, business_payload):
        created = await create_business(client, business_payload)
        assert created["plan"] == "start"
        assert created["capabilities"]["max_posts_per_week"] == 4
        assert created["capabilities"]["instagram"] is False
        assert created["capabilities"]["content_types"] == ["feed_post", "telegram_quiz"]

    async def test_tier_can_be_chosen_on_create(self, client, business_payload):
        created = await create_business(client, {**business_payload, "plan": "pro"})
        assert created["plan"] == "pro"
        assert created["capabilities"]["video"] is True
        assert "reels_script" in created["capabilities"]["content_types"]

    async def test_upgrading_widens_the_capabilities(self, client, business_payload):
        created = await create_business(client, business_payload)
        response = await client.patch(
            f"/api/v1/businesses/{created['id']}", json={"plan": "standard"}
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["plan"] == "standard"
        assert data["capabilities"]["instagram"] is True
        assert data["capabilities"]["video"] is False

    async def test_list_can_be_filtered_by_tier(self, client, business_payload):
        start = await create_business(client, business_payload)
        pro = await create_business(
            client, {**business_payload, "name": "Pro Academy", "plan": "pro"}
        )

        response = await client.get("/api/v1/businesses", params={"plan": "pro"})
        assert response.status_code == 200, response.text
        ids = [row["id"] for row in response.json()["data"]]
        assert pro["id"] in ids
        assert start["id"] not in ids

    async def test_an_unknown_tier_is_rejected(self, client, business_payload):
        response = await client.post(
            "/api/v1/businesses", json={**business_payload, "plan": "enterprise"}
        )
        assert response.status_code == 422

    async def test_a_granted_override_shows_up_in_capabilities(self, client, business_payload):
        payload = {
            **business_payload,
            "settings": {**business_payload["settings"], "plan_overrides": {"video": True}},
        }
        created = await create_business(client, payload)
        assert created["plan"] == "start"
        assert created["capabilities"]["video"] is True
        assert created["capabilities"]["instagram"] is False
