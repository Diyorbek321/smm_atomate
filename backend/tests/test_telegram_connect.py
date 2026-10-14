"""Connecting a client's channel from the dashboard.

The admin types one thing — the channel — and makes the bot an admin of the
channel and of its discussion group. Everything else is asked of Telegram: the
channel's numeric id, the group it is linked to, and whether the bot really has
the rights it needs. Each check comes back as its own step, because "it does not
work" is useless to someone standing in a client's office.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from app.core.exceptions import PublishError
from app.services.telegram_connect import check_channel, normalise_channel

BOT_ID = 777
CHANNEL = {"id": -1001111, "type": "channel", "title": "Shanghai School",
           "username": "shanghai_school", "linked_chat_id": -1002222}
ADMIN_POSTER = {"status": "administrator", "can_post_messages": True}


class FakeTelegram:
    def __init__(self, *, chat: dict | None = CHANNEL,
                 members: dict[int, dict] | None = None) -> None:
        self.chat = chat
        self.members = members if members is not None else {
            -1001111: ADMIN_POSTER, -1002222: {"status": "administrator"}}

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if method == "getChat":
            if self.chat is None:
                raise PublishError("telegram", "getChat failed [400]: Bad Request: chat not found")
            return self.chat
        if method == "getChatMember":
            assert payload["user_id"] == BOT_ID
            member = self.members.get(int(payload["chat_id"]))
            if member is None:
                raise PublishError("telegram", "getChatMember failed [403]: bot is not a member")
            return member
        raise AssertionError(method)


async def run(**kwargs) -> Any:
    return await check_channel(FakeTelegram(**kwargs), "@shanghai_school", bot_id=BOT_ID)


class TestNormaliseChannel:
    @pytest.mark.parametrize("raw", [
        "@shanghai_school", "shanghai_school", " https://t.me/shanghai_school ",
        "t.me/shanghai_school/", "https://t.me/shanghai_school/15",
    ])
    def test_every_way_people_paste_a_channel(self, raw):
        assert normalise_channel(raw) == "@shanghai_school"

    def test_a_numeric_id_is_kept(self):
        assert normalise_channel("-1001111") == "-1001111"

    @pytest.mark.parametrize("raw", ["", "  ", "@ab", "https://example.com/x", "t.me/+invite"])
    def test_nonsense_is_refused(self, raw):
        assert normalise_channel(raw) == ""


class TestCheckChannel:
    async def test_everything_in_place(self):
        result = await run()
        assert result.ok and result.comments_ok
        assert result.channel_id == "-1001111"
        assert result.discussion_id == "-1002222"
        assert result.title == "Shanghai School"
        assert all(step.ok for step in result.steps)

    async def test_an_unknown_channel_stops_at_the_first_step(self):
        result = await run(chat=None)
        assert not result.ok
        assert [s.ok for s in result.steps] == [False]

    async def test_a_group_is_not_a_channel(self):
        result = await run(chat={**CHANNEL, "type": "supergroup"})
        assert not result.ok

    async def test_bot_not_admin_of_the_channel(self):
        result = await run(members={-1001111: {"status": "member"}})
        assert not result.ok
        assert not result.steps[1].ok

    async def test_admin_without_the_right_to_post(self):
        result = await run(members={
            -1001111: {"status": "administrator", "can_post_messages": False},
            -1002222: {"status": "administrator"}})
        assert not result.ok

    async def test_no_discussion_group_still_publishes_but_does_not_answer(self):
        result = await run(chat={k: v for k, v in CHANNEL.items() if k != "linked_chat_id"})
        assert result.ok and not result.comments_ok
        assert result.discussion_id == ""

    async def test_bot_missing_from_the_discussion_group(self):
        result = await run(members={-1001111: ADMIN_POSTER})
        assert result.ok and not result.comments_ok
        assert result.discussion_id == ""

    async def test_a_plain_member_of_the_group_cannot_hear_comments(self):
        result = await run(members={-1001111: ADMIN_POSTER, -1002222: {"status": "member"}})
        assert result.ok and not result.comments_ok

    async def test_an_unparseable_channel_makes_no_call(self):
        result = await check_channel(FakeTelegram(), "nonsense here", bot_id=BOT_ID)
        assert not result.ok and len(result.steps) == 1


async def create_business(client, payload: dict) -> dict:
    response = await client.post("/api/v1/businesses", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.fixture
def telegram(monkeypatch):
    """The Bot API, answered by :class:`FakeTelegram` with the platform token."""
    from app.core.config import settings
    from app.services.telegram_publisher import TelegramPublisher

    # The test database outlives a test, and a channel may belong to one
    # business only — so every test gets channel ids of its own.
    channel, group = (-1000000000000 - random.randrange(10**9) for _ in range(2))
    fake = FakeTelegram(
        chat={**CHANNEL, "id": channel, "linked_chat_id": group,
              "username": f"chan{abs(channel) % 10**8}"},
        members={channel: ADMIN_POSTER, group: {"status": "administrator"}},
    )
    fake.channel, fake.group = channel, group

    async def _call(self, method, payload, files=None):
        if method == "getMe":
            return {"id": BOT_ID, "username": "smm_bot"}
        return await fake._call(method, payload)

    monkeypatch.setattr(settings, "telegram_bot_token", f"{BOT_ID}:platform-token")
    monkeypatch.setattr(TelegramPublisher, "_call", _call)
    return fake


class TestConnectEndpoint:
    async def test_names_the_bot_to_add(self, client, business_payload, telegram):
        business = await create_business(client, business_payload)
        response = await client.get(f"/api/v1/businesses/{business['id']}/telegram/bot")
        assert response.json()["data"]["username"] == "smm_bot"

    async def test_a_ready_channel_is_saved_with_its_group(self, client, business_payload, telegram):
        business = await create_business(client, business_payload)
        response = await client.post(f"/api/v1/businesses/{business['id']}/telegram/connect",
                                     json={"channel": f"t.me/{telegram.chat['username']}"})
        data = response.json()["data"]
        assert data["saved"] and data["comments_ok"]

        creds = (await client.get(f"/api/v1/businesses/{business['id']}/credentials")).json()["data"]
        assert creds["tg_channel_id"] == str(telegram.channel)
        assert creds["tg_discussion_chat_id"] == str(telegram.group)
        assert creds["telegram_ready"] is True

    async def test_a_failed_check_saves_nothing(self, client, business_payload, telegram):
        telegram.members = {}
        business = await create_business(client, business_payload)
        response = await client.post(f"/api/v1/businesses/{business['id']}/telegram/connect",
                                     json={"channel": str(telegram.channel)})
        data = response.json()["data"]
        assert not data["saved"]
        assert [s["ok"] for s in data["steps"]] == [True, False]
        creds = (await client.get(f"/api/v1/businesses/{business['id']}/credentials")).json()["data"]
        assert not creds["tg_channel_id"]

    async def test_a_channel_cannot_belong_to_two_businesses(self, client, business_payload, telegram):
        first = await create_business(client, business_payload)
        second = await create_business(client, {**business_payload, "name": "Other Academy x1"})
        url = "/api/v1/businesses/{}/telegram/connect"
        assert (await client.post(url.format(first["id"]), json={"channel": str(telegram.channel)})).json()["data"]["saved"]
        response = await client.post(url.format(second["id"]), json={"channel": str(telegram.channel)})
        assert response.status_code == 409
