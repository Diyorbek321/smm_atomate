"""Telegram chatbot: the business's own bot answers DMs and channel comments.

The platform bot is the admins' workbench and it polls; a business's chatbot is
the public face and it is pushed to by webhook. The two must never share a
token — a webhook on the platform token silently stops the admin bot.

What matters here is who gets answered. A stranger in a DM, yes. A comment
under one of *this* business's channel posts, yes. A side conversation in the
discussion group, the channel itself, another bot, or a group somebody added
the bot to — no, because every answer costs a model call and speaks for a
brand.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.telegram_chat import (
    belongs_to_channel,
    parse_update,
    webhook_secret,
)

BIZ = uuid.UUID("eec7baec-846c-415e-a646-ea17b4608700")
CHANNEL = {"id": -1001111, "type": "channel", "username": "shanghai_school"}
GROUP = {"id": -1002222, "type": "supergroup"}
USER = {"id": 42, "is_bot": False, "first_name": "Ali", "username": "ali"}


def dm(text: str, **extra) -> dict:
    return {"update_id": 1, "message": {
        "message_id": 10, "chat": {"id": 42, "type": "private"},
        "from": USER, "text": text, **extra}}


def comment(text: str, *, parent: dict | None = None, **extra) -> dict:
    parent = parent if parent is not None else {
        "message_id": 5, "chat": GROUP, "sender_chat": CHANNEL,
        "is_automatic_forward": True, "text": "Yangi guruh ochildi"}
    return {"update_id": 2, "message": {
        "message_id": 11, "chat": GROUP, "from": USER, "text": text,
        "reply_to_message": parent, **extra}}


class TestWebhookSecret:
    def test_is_stable_per_business(self):
        assert webhook_secret(BIZ) == webhook_secret(BIZ)

    def test_differs_between_businesses(self):
        assert webhook_secret(BIZ) != webhook_secret(uuid.uuid4())

    def test_uses_only_characters_telegram_accepts(self):
        secret = webhook_secret(BIZ)
        assert 1 <= len(secret) <= 256
        assert all(c.isalnum() or c in "_-" for c in secret)


class TestDirectMessages:
    def test_a_question_is_answerable(self):
        event = parse_update(dm("Narxi qancha?"))
        assert event is not None
        assert (event.kind, event.chat_id, event.user_id, event.text) == (
            "message", 42, 42, "Narxi qancha?")
        assert event.username == "ali"

    def test_start_is_a_greeting_not_a_question(self):
        event = parse_update(dm("/start"))
        assert event is not None and event.kind == "start"

    def test_start_with_a_deep_link_payload_is_still_a_greeting(self):
        event = parse_update(dm("/start from_post_12"))
        assert event is not None and event.kind == "start"

    def test_other_commands_are_ignored(self):
        assert parse_update(dm("/help")) is None

    def test_another_bot_is_ignored(self):
        update = dm("salom")
        update["message"]["from"] = {**USER, "is_bot": True}
        assert parse_update(update) is None

    def test_a_message_without_text_is_ignored(self):
        update = dm("")
        update["message"].pop("text")
        update["message"]["sticker"] = {"file_id": "x"}
        assert parse_update(update) is None

    def test_a_caption_counts_as_text(self):
        update = dm("")
        update["message"].pop("text")
        update["message"]["caption"] = "Bu kurs bormi?"
        event = parse_update(update)
        assert event is not None and event.text == "Bu kurs bormi?"

    def test_an_edited_message_is_not_answered_twice(self):
        assert parse_update({"update_id": 3, "edited_message": dm("x")["message"]}) is None

    def test_garbage_is_skipped_not_raised(self):
        assert parse_update({}) is None
        assert parse_update({"message": "nope"}) is None


class TestChannelComments:
    def test_a_reply_to_the_channel_post_is_a_comment(self):
        event = parse_update(comment("Qachon boshlanadi?"))
        assert event is not None
        assert event.kind == "comment"
        assert (event.chat_id, event.message_id) == (GROUP["id"], 11)
        assert event.channel_id == CHANNEL["id"]
        assert event.channel_username == "shanghai_school"

    def test_a_reply_to_another_comment_is_left_to_people(self):
        other = {"message_id": 9, "chat": GROUP, "from": {**USER, "id": 7}, "text": "men ham"}
        assert parse_update(comment("rost", parent=other)) is None

    def test_a_plain_group_message_is_ignored(self):
        update = comment("salom")
        update["message"].pop("reply_to_message")
        assert parse_update(update) is None

    def test_the_channel_posting_into_its_own_thread_is_ignored(self):
        assert parse_update(comment("e'lon", sender_chat=CHANNEL)) is None


class TestBelongsToChannel:
    def test_matches_by_username(self):
        event = parse_update(comment("?"))
        assert belongs_to_channel(event, channel_ref="@Shanghai_School", discussion_id=None)

    def test_matches_by_numeric_id(self):
        event = parse_update(comment("?"))
        assert belongs_to_channel(event, channel_ref="-1001111", discussion_id=None)

    def test_matches_by_discussion_group(self):
        event = parse_update(comment("?"))
        assert belongs_to_channel(event, channel_ref="@other", discussion_id="-1002222")

    def test_a_foreign_channel_is_refused(self):
        event = parse_update(comment("?"))
        assert not belongs_to_channel(event, channel_ref="@someone_else", discussion_id=None)

    def test_no_configured_channel_refuses_comments(self):
        event = parse_update(comment("?"))
        assert not belongs_to_channel(event, channel_ref=None, discussion_id=None)

    def test_a_dm_always_belongs(self):
        event = parse_update(dm("?"))
        assert belongs_to_channel(event, channel_ref=None, discussion_id=None)


class TestWebhookEndpoint:
    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import app

        queued: list[tuple] = []
        monkeypatch.setattr(
            "app.tasks.dispatch.enqueue",
            lambda name, *a, **kw: queued.append((name, a, kw)) or "task-1",
        )
        client = TestClient(app)
        client.queued = queued
        return client

    def url(self, business_id=BIZ) -> str:
        return f"/telegram/chat/{business_id}/webhook"

    def test_a_correct_secret_queues_the_message(self, client):
        response = client.post(
            self.url(), json=dm("Narxi?"),
            headers={"X-Telegram-Bot-Api-Secret-Token": webhook_secret(BIZ)},
        )
        assert response.status_code == 200
        assert len(client.queued) == 1
        name, args, _ = client.queued[0]
        assert name == "app.tasks.telegram_chat.handle_update"
        assert args[0] == str(BIZ)

    def test_a_missing_secret_is_refused(self, client):
        response = client.post(self.url(), json=dm("Narxi?"))
        assert response.status_code == 403
        assert client.queued == []

    def test_another_business_secret_is_refused(self, client):
        response = client.post(
            self.url(), json=dm("Narxi?"),
            headers={"X-Telegram-Bot-Api-Secret-Token": webhook_secret(uuid.uuid4())},
        )
        assert response.status_code == 403

    def test_an_unanswerable_update_is_acknowledged_without_work(self, client):
        response = client.post(
            self.url(), json={"update_id": 9, "edited_message": dm("x")["message"]},
            headers={"X-Telegram-Bot-Api-Secret-Token": webhook_secret(BIZ)},
        )
        assert response.status_code == 200
        assert client.queued == []

    def test_a_malformed_business_id_is_not_found(self, client):
        response = client.post("/telegram/chat/not-a-uuid/webhook", json=dm("x"))
        assert response.status_code == 404
