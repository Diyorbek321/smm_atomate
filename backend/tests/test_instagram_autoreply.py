"""Instagram auto-reply: the tier sold it, only Telegram delivered it.

`lead_autoreply` was checked in exactly one place — `app/bot/handlers/lead.py`
— so a business paying for auto-reply got it on Telegram and silence on
Instagram, where most of the strangers actually are.

The two things worth holding here are not the happy path. A public webhook is
reachable by anyone, so an unsigned body must never produce a reply from a
brand account. And a comment earns exactly one private message from Meta, ever,
so it must not be spent on a greeting.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.services.instagram_messaging import (
    COMMENT_LIMIT,
    DM_LIMIT,
    InboundEvent,
    parse,
    verify_signature,
)
from app.tasks.instagram import find_phone

SECRET = "test-app-secret"


def signed(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestOnlyMetaGetsAnswered:
    """A public URL: everyone can POST to it, nobody else may drive replies."""

    def test_a_correct_signature_passes(self):
        body = b'{"entry":[]}'
        assert verify_signature(body, signed(body), SECRET)

    def test_an_unsigned_body_is_refused(self):
        assert not verify_signature(b'{"entry":[]}', None, SECRET)

    def test_a_forged_signature_is_refused(self):
        assert not verify_signature(b'{"entry":[]}', "sha256=" + "0" * 64, SECRET)

    def test_a_body_signed_with_another_secret_is_refused(self):
        body = b'{"entry":[]}'
        assert not verify_signature(body, signed(body, "someone-elses"), SECRET)

    def test_a_tampered_body_is_refused(self):
        header = signed(b'{"entry":[]}', SECRET)
        assert not verify_signature(b'{"entry":[{"id":"evil"}]}', header, SECRET)

    def test_an_unset_app_secret_refuses_everything(self):
        """Better to answer nobody than to answer anybody."""
        body = b'{"entry":[]}'
        assert not verify_signature(body, signed(body, ""), "")

    def test_a_non_sha256_scheme_is_refused(self):
        body = b'{"entry":[]}'
        digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert not verify_signature(body, f"sha1={digest}", SECRET)


class TestParsingWhatMetaSends:
    def test_a_direct_message_is_answerable(self):
        events = parse({"entry": [{"id": "acc", "messaging": [
            {"sender": {"id": "u1"}, "message": {"text": "Narxi qancha?"}}]}]})
        assert [(e.kind, e.sender_id, e.answerable) for e in events] == [
            ("message", "u1", True)]

    def test_a_comment_carries_its_id_for_the_reply(self):
        events = parse({"entry": [{"id": "acc", "changes": [
            {"field": "comments", "value": {
                "id": "c1", "text": "Qachon boshlanadi?",
                "from": {"id": "u2", "username": "ali"}}}]}]})
        assert events[0].comment_id == "c1"
        assert events[0].username == "ali"

    def test_our_own_reply_coming_back_is_not_answered_again(self):
        """Echoes arrive on the same webhook; answering them is a loop."""
        events = parse({"entry": [{"id": "acc", "messaging": [
            {"sender": {"id": "acc"}, "message": {"text": "Salom", "is_echo": True}}]}]})
        assert not events[0].answerable

    def test_the_account_commenting_on_itself_is_not_answered(self):
        events = parse({"entry": [{"id": "acc", "changes": [
            {"field": "comments", "value": {
                "id": "c9", "text": "Rahmat!", "from": {"id": "acc"}}}]}]})
        assert not events[0].answerable

    def test_an_empty_message_is_not_answered(self):
        events = parse({"entry": [{"id": "acc", "messaging": [
            {"sender": {"id": "u1"}, "message": {"text": "   "}}]}]})
        assert not events[0].answerable

    @pytest.mark.parametrize("payload", [
        {}, {"entry": []}, {"entry": [{"id": "a"}]},
        {"entry": [{"id": "a", "changes": [{"field": "mentions", "value": {}}]}]},
        {"entry": [{"id": "a", "messaging": [{}]}]},
    ])
    def test_an_unfamiliar_shape_is_skipped_not_raised(self, payload):
        """Meta adds event types without warning.

        A webhook that 500s on an unknown payload gets itself disabled, losing
        the events it could have handled.
        """
        assert isinstance(parse(payload), list)


class TestFindingAPhoneInASentence:
    """A DM is not a form; the number arrives inside a sentence or not at all."""

    @pytest.mark.parametrize("text", [
        "raqamim +998 90 123 45 67",
        "901234567 ga yozing",
        "+998901234567",
        "tel: 90 123-45-67",
    ])
    def test_the_shapes_people_actually_type(self, text):
        assert find_phone(text) == "+998901234567"

    @pytest.mark.parametrize("text", ["narxi qancha?", "", "2026-yilda boshlanadi"])
    def test_no_number_means_no_number(self, text):
        assert find_phone(text) == ""


class TestTheWebhookEndpoint:
    @pytest.fixture(autouse=True)
    def _secret(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "meta_app_secret", SECRET)
        monkeypatch.setattr(settings, "meta_verify_token", "verify-me")

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from app.main import app

        return TestClient(app)

    def test_the_handshake_echoes_the_challenge(self, client):
        response = client.get("/instagram/webhook", params={
            "hub.mode": "subscribe", "hub.verify_token": "verify-me",
            "hub.challenge": "12345"})
        assert response.status_code == 200
        assert response.text == "12345"

    def test_a_wrong_verify_token_is_refused(self, client):
        response = client.get("/instagram/webhook", params={
            "hub.mode": "subscribe", "hub.verify_token": "guess",
            "hub.challenge": "12345"})
        assert response.status_code == 403

    def test_an_unconfigured_webhook_refuses_the_handshake(self, client, monkeypatch):
        """Looking connected while accepting anyone is worse than being off."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "meta_verify_token", "")
        response = client.get("/instagram/webhook", params={
            "hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "x"})
        assert response.status_code == 403

    def test_an_unsigned_delivery_is_refused(self, client):
        assert client.post("/instagram/webhook", json={"entry": []}).status_code == 403

    def test_a_signed_delivery_is_accepted(self, client):
        body = json.dumps({"entry": []}).encode()
        response = client.post("/instagram/webhook", content=body,
                               headers={"X-Hub-Signature-256": signed(body),
                                        "Content-Type": "application/json"})
        assert response.status_code == 200

    def test_unreadable_json_is_accepted_rather_than_retried_forever(self, client):
        """A body we cannot parse will not parse on the fourth delivery either."""
        body = b"not json"
        response = client.post("/instagram/webhook", content=body,
                               headers={"X-Hub-Signature-256": signed(body)})
        assert response.status_code == 200

    def test_a_real_message_is_queued_not_handled_inline(self, client, monkeypatch):
        """Meta retries a slow webhook and eventually disables it."""
        queued: list[tuple] = []
        import app.tasks.dispatch as dispatch

        monkeypatch.setattr(dispatch, "enqueue",
                            lambda name, *a, **k: queued.append((name, a, k)) or "task-1")
        body = json.dumps({"entry": [{"id": "acc", "messaging": [
            {"sender": {"id": "u1"}, "message": {"text": "Narxi qancha?"}}]}]}).encode()
        response = client.post("/instagram/webhook", content=body,
                               headers={"X-Hub-Signature-256": signed(body),
                                        "Content-Type": "application/json"})
        assert response.status_code == 200
        assert queued and queued[0][0] == "app.tasks.instagram.handle_event"


class TestLimits:
    def test_a_dm_and_a_comment_are_not_held_to_the_same_length(self):
        # A wall of text under a public post reads as spam before it reads as
        # helpful; a DM has room to actually answer.
        assert COMMENT_LIMIT < DM_LIMIT

    def test_an_event_with_no_sender_is_not_answerable(self):
        assert not InboundEvent(kind="message", text="salom").answerable


class TestTheReplyItself:
    async def test_a_failed_model_leaves_it_for_a_human(self, monkeypatch):
        """`""` means "a person should answer this".

        A brand account replying "I don't know" under its own post is worse
        than the same post with no reply and a notification to the owner.
        """
        from app.agents.reply import ReplyAgent
        from tests.test_agents import make_business, make_knowledge

        async def boom(*args, **kwargs):
            raise RuntimeError("model down")

        agent = ReplyAgent(session=None)
        monkeypatch.setattr(agent, "ask_text", boom)
        assert await agent.answer(make_business(), make_knowledge(), "Narxi?") == ""

    async def test_a_public_comment_is_told_it_is_public(self, monkeypatch):
        from app.agents.reply import ReplyAgent
        from tests.test_agents import make_business, make_knowledge

        prompts: list[str] = []

        async def fake(prompt, **kwargs):
            prompts.append(prompt)
            return "Javob."

        agent = ReplyAgent(session=None)
        monkeypatch.setattr(agent, "ask_text", fake)
        await agent.answer(make_business(), make_knowledge(), "Qancha?", public=True)
        assert "OCHIQ komment" in prompts[0]
        await agent.answer(make_business(), make_knowledge(), "Qancha?", public=False)
        assert "shaxsiy xabar" in prompts[1]

    async def test_a_long_answer_is_cut_to_something_readable(self, monkeypatch):
        from app.agents.reply import MAX_CHARS, ReplyAgent
        from tests.test_agents import make_business, make_knowledge

        async def fake(prompt, **kwargs):
            return "a" * (MAX_CHARS * 3)

        agent = ReplyAgent(session=None)
        monkeypatch.setattr(agent, "ask_text", fake)
        answer = await agent.answer(make_business(), make_knowledge(), "?")
        assert len(answer) == MAX_CHARS


class TestItIsWiredToRun:
    def test_the_task_is_registered(self):
        import app.tasks.instagram  # noqa: F401
        from app.tasks.celery_app import celery_app

        assert "app.tasks.instagram.handle_event" in celery_app.tasks

    def test_it_does_not_queue_behind_a_clip_render(self):
        """Somebody is waiting on this reply; a promo render takes minutes."""
        from app.tasks.celery_app import celery_app

        routes = celery_app.conf.task_routes
        assert routes["app.tasks.instagram.*"]["queue"] == "publishing"

    def test_it_never_retries_itself(self):
        """Meta retries the delivery. Retrying here too is four identical
        public replies under one comment."""
        from app.tasks.instagram import handle_event

        assert handle_event.max_retries == 0
