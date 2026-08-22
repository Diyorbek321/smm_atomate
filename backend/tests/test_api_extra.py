"""Remaining API surface: inline generation, deletes, webhook, prompt studio."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
        "headline": "Sarlavha",
        "caption_tg": "Matn",
        "caption_ig": "Matn",
        "hashtags": [],
        "scheduled_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
        "status": "pending_review",
    }
    payload.update(overrides)
    return payload


class TestInlineGeneration:
    @pytest.fixture
    def stub_pipeline(self, monkeypatch, patch_global_session_scope):
        """No broker + a fake pipeline: exercises the in-process fallback."""
        from app.models.content_item import ContentItem
        from app.models.content_plan import ContentPlan
        from app.models.enums import (
            ContentItemStatus,
            ContentPillar,
            ContentPlanStatus,
            ContentType,
            Platform,
        )
        from app.utils.dates import utcnow

        monkeypatch.setattr("app.api.v1.generation._enqueue", lambda *a, **k: None)
        created: dict[str, list] = {"plans": [], "items": []}

        def _item(business_id, topic="IELTS"):
            return ContentItem(
                business_id=business_id,
                content_type=ContentType.FEED_POST,
                pillar=ContentPillar.SALES,
                platform=Platform.TELEGRAM,
                topic=topic,
                headline=f"Inline {topic}",
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

        async def fake_plan(self, business_id, **kwargs):
            from app.agents.orchestrator import PipelineResult

            plan = ContentPlan(
                business_id=business_id,
                title="Inline reja",
                year=2026,
                week_number=42,
                month_number=10,
                starts_on=utcnow().date(),
                ends_on=utcnow().date() + timedelta(days=6),
                status=ContentPlanStatus.PENDING_REVIEW,
                strategy={},
                notes="",
            )
            plan.items = []
            self.session.add(plan)
            await self.session.flush()
            item = _item(business_id)
            plan.items.append(item)
            await self.session.flush()
            created["plans"].append(plan.id)
            return PipelineResult(plan=plan, items=[item])

        async def fake_single(self, business_id, **kwargs):
            item = _item(business_id, kwargs.get("topic") or "IELTS")
            self.session.add(item)
            await self.session.flush()
            created["items"].append(item.id)
            return item

        async def no_push(*args, **kwargs):
            return 0

        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.generate_plan", fake_plan)
        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.generate_single", fake_single)
        monkeypatch.setattr("app.bot.notifier.push_items_for_review", no_push)
        monkeypatch.setattr("app.bot.notifier.push_plan_summary", no_push)
        return created

    async def test_plan_runs_in_process_without_a_broker(
        self, client, business_payload, stub_pipeline
    ):
        business = await create_business(client, business_payload)
        response = await client.post(
            "/api/v1/generate/plan", json={"business_id": business["id"], "posts_count": 4}
        )
        assert response.json()["data"]["status"] == "running_inline"

        plans = await client.get("/api/v1/plans", params={"business_id": business["id"]})
        assert plans.json()["meta"]["total"] == 1

    async def test_item_runs_in_process_without_a_broker(
        self, client, business_payload, stub_pipeline
    ):
        business = await create_business(client, business_payload)
        response = await client.post(
            "/api/v1/generate/item",
            json={"business_id": business["id"], "topic": "Sentabr", "content_type": "feed_post"},
        )
        assert response.json()["data"]["status"] == "running_inline"

        items = await client.get("/api/v1/items", params={"business_id": business["id"]})
        assert items.json()["meta"]["total"] == 1
        assert items.json()["data"][0]["headline"] == "Inline Sentabr"

    async def test_regenerate_runs_in_process(
        self, client, business_payload, monkeypatch, patch_global_session_scope
    ):
        monkeypatch.setattr("app.api.v1.generation._enqueue", lambda *a, **k: None)

        async def fake_regenerate(self, item, *, instruction="", regenerate_image=False):
            item.headline = "Qayta yozilgan"
            item.regeneration_count += 1
            return item

        monkeypatch.setattr("app.agents.orchestrator.ContentPipeline.regenerate", fake_regenerate)

        business = await create_business(client, business_payload)
        created = await client.post("/api/v1/items", json=item_payload(business["id"]))
        item_id = created.json()["data"]["id"]

        response = await client.post(
            f"/api/v1/generate/item/{item_id}/regenerate", json={"instruction": "kuchliroq"}
        )
        assert response.json()["data"]["status"] == "done"

        detail = await client.get(f"/api/v1/items/{item_id}")
        assert detail.json()["data"]["headline"] == "Qayta yozilgan"

    async def test_task_status_is_reported(self, client):
        response = await client.get("/api/v1/generate/task/does-not-exist")
        assert response.status_code == 200
        assert response.json()["data"]["task_id"] == "does-not-exist"


class TestMutations:
    async def test_update_item_fields(self, client, business_payload):
        business = await create_business(client, business_payload)
        created = await client.post("/api/v1/items", json=item_payload(business["id"]))
        item_id = created.json()["data"]["id"]

        new_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        response = await client.patch(
            f"/api/v1/items/{item_id}",
            json={"headline": "Yangi sarlavha", "scheduled_at": new_time, "hashtags": ["#yangi"]},
        )
        data = response.json()["data"]
        assert data["headline"] == "Yangi sarlavha"
        assert data["hashtags"] == ["#yangi"]

    async def test_delete_item(self, client, business_payload):
        business = await create_business(client, business_payload)
        created = await client.post("/api/v1/items", json=item_payload(business["id"]))
        item_id = created.json()["data"]["id"]

        assert (await client.delete(f"/api/v1/items/{item_id}")).status_code == 200
        assert (await client.get(f"/api/v1/items/{item_id}")).status_code == 404

    async def test_delete_plan_cascades_to_items(self, client, session, business_payload):
        from app.models.content_plan import ContentPlan
        from app.models.enums import ContentPlanStatus
        from app.utils.dates import utcnow

        business = await create_business(client, business_payload)
        plan = ContentPlan(
            business_id=business["id"], title="Delete me", year=2026, week_number=43,
            month_number=10, starts_on=utcnow().date(), ends_on=utcnow().date(),
            status=ContentPlanStatus.DRAFT, strategy={}, notes="",
        )
        session.add(plan)
        await session.commit()
        plan_id = str(plan.id)

        await client.post("/api/v1/items", json=item_payload(business["id"], content_plan_id=plan_id))

        assert (await client.delete(f"/api/v1/plans/{plan_id}")).status_code == 200
        remaining = await client.get("/api/v1/items", params={"content_plan_id": plan_id})
        assert remaining.json()["meta"]["total"] == 0

    async def test_update_plan_metadata(self, client, session, business_payload):
        from app.models.content_plan import ContentPlan
        from app.models.enums import ContentPlanStatus
        from app.utils.dates import utcnow

        business = await create_business(client, business_payload)
        plan = ContentPlan(
            business_id=business["id"], title="Old", year=2026, week_number=44, month_number=11,
            starts_on=utcnow().date(), ends_on=utcnow().date(),
            status=ContentPlanStatus.DRAFT, strategy={}, notes="",
        )
        session.add(plan)
        await session.commit()

        response = await client.patch(
            f"/api/v1/plans/{plan.id}", json={"title": "New title", "notes": "izoh"}
        )
        assert response.json()["data"]["title"] == "New title"

    async def test_admin_removal_checks_ownership(self, client, business_payload):
        first = await create_business(client, business_payload)
        second = await create_business(
            client, {**business_payload, "name": business_payload["name"] + " 2"}
        )
        created = await client.post(
            f"/api/v1/businesses/{first['id']}/admins", json={"telegram_user_id": 5551}
        )
        admin_id = created.json()["data"]["id"]

        wrong = await client.delete(f"/api/v1/businesses/{second['id']}/admins/{admin_id}")
        assert wrong.status_code == 404

        right = await client.delete(f"/api/v1/businesses/{first['id']}/admins/{admin_id}")
        assert right.status_code == 200


class TestKnowledgeIngest:
    async def test_ingest_updates_the_profile(self, client, business_payload, monkeypatch):
        from app.agents.onboarding import OnboardingResult
        from app.schemas.knowledge_base import KnowledgeExtraction

        async def fake_ingest(self, business, knowledge, message, source="api"):
            knowledge.phone = "+998900000000"
            return OnboardingResult(
                extraction=KnowledgeExtraction(),
                next_question="Narxlar qanday?",
                completeness=0.42,
                updated_fields=["phone"],
                summary="Telefon qo'shildi",
            )

        monkeypatch.setattr("app.agents.onboarding.OnboardingAgent.ingest", fake_ingest)

        business = await create_business(client, business_payload)
        response = await client.post(
            f"/api/v1/businesses/{business['id']}/knowledge/ingest",
            json={"text": "Telefonimiz +998900000000"},
        )
        data = response.json()["data"]
        assert data["updated_fields"] == ["phone"]
        assert data["next_question"] == "Narxlar qanday?"

        knowledge = await client.get(f"/api/v1/businesses/{business['id']}/knowledge")
        assert knowledge.json()["data"]["phone"] == "+998900000000"


class TestPromptStudio:
    async def test_agents_and_defaults(self, client):
        agents = (await client.get("/api/v1/prompts/agents")).json()["data"]
        assert "strategist" in agents and "editor" in agents

        for agent in agents:
            default = (await client.get(f"/api/v1/prompts/defaults/{agent}")).json()["data"]
            assert default["system_prompt"], f"{agent} has no default prompt"

    async def test_crud_and_filtering(self, client, business_payload):
        business = await create_business(client, business_payload)
        created = await client.post(
            "/api/v1/prompts",
            json={
                "business_id": business["id"],
                "name": "sales-tone",
                "agent": "copywriter",
                "pillar": "sales",
                "system_prompt": "Sotuv postlarini kuchliroq yoz.",
            },
        )
        prompt = created.json()["data"]
        assert prompt["pillar"] == "sales"

        listing = await client.get("/api/v1/prompts", params={"business_id": business["id"]})
        assert listing.json()["meta"]["total"] == 1

        filtered = await client.get("/api/v1/prompts", params={"agent": "editor"})
        assert all(row["agent"] == "editor" for row in filtered.json()["data"])

        assert (await client.delete(f"/api/v1/prompts/{prompt['id']}")).status_code == 200
        assert (await client.get(f"/api/v1/prompts/{prompt['id']}")).status_code == 404

    async def test_rollback_to_unknown_version(self, client):
        created = await client.post(
            "/api/v1/prompts",
            json={"name": f"rb-{datetime.now(UTC).timestamp()}", "system_prompt": "Birinchi matn"},
        )
        prompt_id = created.json()["data"]["id"]
        assert (await client.post(f"/api/v1/prompts/{prompt_id}/rollback/99")).status_code == 404


class TestPromptOverrides:
    async def test_agent_prefers_a_stored_prompt(self, client, session, business_payload):
        """A DB override must win over the built-in system prompt."""
        from app.agents.copywriter import CopywriterAgent
        from app.agents.prompts import COPYWRITER_SYSTEM
        from app.models.enums import ContentPillar

        business = await create_business(client, business_payload)
        await client.post(
            "/api/v1/prompts",
            json={
                "business_id": business["id"],
                "name": f"override-{datetime.now(UTC).timestamp()}",
                "agent": "copywriter",
                "pillar": "sales",
                "system_prompt": "MAXSUS KO'RSATMA",
            },
        )

        import uuid as _uuid

        agent = CopywriterAgent(session=session)
        chosen = await agent.system_prompt(
            COPYWRITER_SYSTEM,
            business_id=_uuid.UUID(business["id"]),
            pillar=ContentPillar.SALES,
        )
        assert chosen == "MAXSUS KO'RSATMA"

        # A different pillar must not pick up the sales-specific override.
        fallback = await agent.system_prompt(
            COPYWRITER_SYSTEM,
            business_id=_uuid.UUID(business["id"]),
            pillar=ContentPillar.INTERACTIVE,
        )
        assert fallback != "MAXSUS KO'RSATMA"


class TestWebhook:
    async def test_wrong_secret_is_forbidden(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "telegram_webhook_secret", "s3cret", raising=False)
        response = await client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "nope"},
        )
        assert response.status_code == 403

    async def test_without_a_dispatcher_it_reports_unavailable(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
        response = await client.post("/telegram/webhook", json={"update_id": 1})
        assert response.status_code == 503


class TestAnalyticsExtras:
    async def test_recent_failures_endpoint(self, client):
        response = await client.get("/api/v1/analytics/failures", params={"hours": 48})
        assert response.status_code == 200
        assert isinstance(response.json()["data"], list)


class TestKnowledgeFileIngest:
    @staticmethod
    def _fake_result(summary: str):
        from app.agents.onboarding import OnboardingResult
        from app.schemas.knowledge_base import KnowledgeExtraction

        return OnboardingResult(
            extraction=KnowledgeExtraction(),
            next_question=None,
            completeness=0.5,
            updated_fields=["prices"],
            summary=summary,
        )

    async def test_pdf_goes_through_the_document_reader(self, client, business_payload, monkeypatch):
        business = await create_business(client, business_payload)
        seen: dict = {}

        async def fake_ingest_document(self, business_, knowledge, data, **kwargs):
            seen.update(kwargs, size=len(data))
            return TestKnowledgeFileIngest._fake_result("PDFdan olindi")

        monkeypatch.setattr(
            "app.agents.onboarding.OnboardingAgent.ingest_document", fake_ingest_document
        )

        response = await client.post(
            f"/api/v1/businesses/{business['id']}/knowledge/ingest-file",
            files={"file": ("narxlar.pdf", b"%PDF-1.4 data", "application/pdf")},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["filename"] == "narxlar.pdf"
        assert data["updated_fields"] == ["prices"]
        assert seen["filename"] == "narxlar.pdf"
        assert seen["mime_type"] == "application/pdf"

    async def test_text_file_routes_through_text_ingest(self, client, business_payload, monkeypatch):
        business = await create_business(client, business_payload)
        seen: dict = {}

        async def fake_ingest(self, business_, knowledge, text, **kwargs):
            seen["text"] = text
            return TestKnowledgeFileIngest._fake_result("Matndan olindi")

        monkeypatch.setattr("app.agents.onboarding.OnboardingAgent.ingest", fake_ingest)

        response = await client.post(
            f"/api/v1/businesses/{business['id']}/knowledge/ingest-file",
            files={"file": ("notes.txt", b"IELTS 600 ming", "text/plain")},
        )
        assert response.status_code == 200, response.text
        assert seen["text"] == "IELTS 600 ming"

    async def test_wrong_file_type_is_rejected(self, client, business_payload):
        business = await create_business(client, business_payload)
        response = await client.post(
            f"/api/v1/businesses/{business['id']}/knowledge/ingest-file",
            files={"file": ("photo.jpg", b"\xff\xd8\xffJPEG", "image/jpeg")},
        )
        assert response.status_code == 422

    async def test_fake_pdf_extension_is_rejected(self, client, business_payload):
        """A .pdf name with non-PDF bytes must not reach the model."""
        business = await create_business(client, business_payload)
        response = await client.post(
            f"/api/v1/businesses/{business['id']}/knowledge/ingest-file",
            files={"file": ("fake.pdf", b"\x00\x01binary", "application/pdf")},
        )
        assert response.status_code == 422


class TestBrandBackdrops:
    async def test_generating_a_library_uses_the_brand_palette(
        self, client, business_payload, tmp_path, monkeypatch
    ):
        from PIL import Image

        from app.services.storage import MediaStorage

        storage = MediaStorage(tmp_path)
        monkeypatch.setattr("app.services.brand_assets.get_storage", lambda: storage)

        business = await create_business(client, business_payload)
        await client.put(
            f"/api/v1/businesses/{business['id']}/knowledge",
            json={"brand_colors": {"bg": "#101820", "accent": "#FF3366"}},
        )

        response = await client.post(f"/api/v1/businesses/{business['id']}/backdrops")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["count"] == 6

        folder = tmp_path / "brand" / business["id"] / "photos"
        files = sorted(folder.glob("*.jpg"))
        assert len(files) == 6
        image = Image.open(files[0])
        assert image.size == (1080, 1920)

        # The library must be this client's, in this client's colours.
        from app.services.brand_assets import photo_library

        assert [p.name for p in photo_library(business["id"])] == [p.name for p in files]
        pixels = list(Image.open(files[2]).convert("RGB").getdata())
        assert any(r > 120 and g < 90 for r, g, _ in pixels), "brend aksenti ko'rinmayapti"
