"""POST /generate/video-prompt over HTTP."""

from __future__ import annotations

import pytest

from app.agents.video_prompt import VideoConcept

pytestmark = pytest.mark.db


async def create_business(client, payload: dict) -> dict:
    response = await client.post("/api/v1/businesses", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.fixture
def fake_model(monkeypatch):
    async def fake(self, *args, **kwargs):
        return VideoConcept(
            title="Sinov",
            concept="Raqam 0 dan 600 ga sanaydi.",
            message="Bir oyda natija",
            scenes=["0–5s: raqam sanaydi", "5–10s: o'qituvchi kartasi", "10–15s: lockup"],
            sound="Zarb va tick",
            closing="Yozing",
        )

    monkeypatch.setattr("app.agents.video_prompt.VideoPromptAgent.ask_json", fake)


class TestVideoPrompt:
    async def test_returns_ready_prompt(self, client, business_payload, fake_model):
        business = await create_business(client, business_payload)
        response = await client.post(
            "/api/v1/generate/video-prompt",
            json={"business_id": business["id"], "goal": "Kuzgi guruh", "format": "showreel",
                  "duration": 15, "aspect": "9:16"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["fallback"] is False
        assert "npx hyperframes skills update" in data["prompt"]
        assert business["name"] in data["prompt"]
        assert data["concept"]["scenes"]

    async def test_rejects_unknown_format(self, client, business_payload, fake_model):
        business = await create_business(client, business_payload)
        response = await client.post(
            "/api/v1/generate/video-prompt",
            json={"business_id": business["id"], "format": "kino"},
        )
        assert response.status_code in (400, 422)

    async def test_requires_business(self, client, fake_model):
        response = await client.post("/api/v1/generate/video-prompt", json={})
        assert response.status_code in (400, 422)

    async def test_listed_in_prompt_studio(self, client):
        agents = (await client.get("/api/v1/prompts/agents")).json()["data"]
        assert "video_prompt" in agents
        default = (await client.get("/api/v1/prompts/defaults/video_prompt")).json()["data"]
        assert "MOTION-REJISSYOR" in default["system_prompt"]
