"""Channel comments answered by the platform bot itself.

A business that publishes through the platform bot has no bot of its own to
point a webhook at — and a webhook on the platform token would stop the admin
bot. So the polling bot hears the discussion group and hands comments to the
same task the webhook feeds. What matters: an aiogram message survives the trip
back into the webhook's shape, and a comment finds the business whose channel
it sits under — never a neighbour's.
"""

from __future__ import annotations

import uuid

from aiogram.types import Message

from app.services.telegram_chat import match_business, message_to_update, parse_update

SHANGHAI = uuid.UUID("eec7baec-846c-415e-a646-ea17b4608700")
POSTCHI = uuid.uuid4()
CHANNEL = {"id": -1001111, "type": "channel", "username": "amoragifts", "title": "Amora"}
GROUP = {"id": -1002222, "type": "supergroup", "title": "Amora chat"}
USER = {"id": 42, "is_bot": False, "first_name": "Ali", "username": "ali"}


def group_message(text: str, *, parent: dict | None = None) -> Message:
    raw = {"message_id": 11, "date": 1760000000, "chat": GROUP, "from": USER, "text": text}
    if parent is not None:
        raw["reply_to_message"] = parent
    return Message.model_validate(raw)


POST = {"message_id": 5, "date": 1760000000, "chat": GROUP, "sender_chat": CHANNEL,
        "is_automatic_forward": True, "text": "Yangi guruh ochildi"}


class TestMessageToUpdate:
    def test_a_comment_keeps_its_shape(self):
        event = parse_update(message_to_update(group_message("Narxi qancha?", parent=POST)))
        assert event is not None
        assert (event.kind, event.chat_id, event.user_id, event.message_id) == (
            "comment", -1002222, 42, 11)
        assert event.channel_username == "amoragifts"
        assert event.full_name == "Ali"

    def test_group_chatter_is_not_a_comment(self):
        assert parse_update(message_to_update(group_message("salom hammaga"))) is None


class TestMatchBusiness:
    def event(self):
        return parse_update(message_to_update(group_message("Narxi?", parent=POST)))

    def test_finds_the_business_by_channel_username(self):
        rows = [(POSTCHI, "@postchi_uz", None), (SHANGHAI, "@AmoraGifts", None)]
        assert match_business(self.event(), rows) == SHANGHAI

    def test_finds_the_business_by_discussion_group(self):
        rows = [(SHANGHAI, None, "-1002222")]
        assert match_business(self.event(), rows) == SHANGHAI

    def test_a_foreign_channel_matches_nobody(self):
        rows = [(POSTCHI, "@postchi_uz", None)]
        assert match_business(self.event(), rows) is None
