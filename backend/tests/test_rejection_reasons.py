"""Keeping the reason a post was rejected.

This system's only route from the owner's taste into the machine is what they
say when something is wrong. The button threw that away: it set the status, the
reviewer and the timestamp, and left `review_notes` empty. The typed path kept
the reason — but people press the button.

The result was measurable. Every rejected item in the database carries the same
note, `«qayta yaratilgani uchun almashtirildi»`, written by the planner when it
supersedes an unapproved week. Not one row holds a sentence from a human.

So the button asks now, and the answer is stored where the typed path already
stores it. What is done with the accumulated reasons is a separate step; this
one exists because that step cannot be built on an empty column.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.states import ReviewStates
from app.models.enums import ContentItemStatus


class _Message:
    def __init__(self):
        self.answers: list[str] = []
        self.chat = SimpleNamespace(id=99)
        self.from_user = SimpleNamespace(id=7)

    async def answer(self, text, **kwargs):
        self.answers.append(text)
        return SimpleNamespace(message_id=1)

    async def edit_reply_markup(self, **kwargs):
        return None

    async def edit_caption(self, **kwargs):
        return None

    async def edit_text(self, **kwargs):
        return None


class _State:
    def __init__(self):
        self.state = None
        self.data: dict = {}

    async def set_state(self, value):
        self.state = value

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.state, self.data = None, {}


def _item():
    return SimpleNamespace(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        status=ContentItemStatus.PENDING_REVIEW,
        review_notes="",
        reviewed_at=None,
        reviewed_by=None,
        topic="Kuzgi qabul",
    )


@pytest.fixture
def wired(monkeypatch):
    """The review module with its database and helpers stubbed out."""
    from app.bot.handlers import review

    item = _item()
    monkeypatch.setattr(review, "_load_item", AsyncMock(return_value=item))
    monkeypatch.setattr(review, "mark_decided", AsyncMock())
    return review, item


@pytest.fixture
def session():
    return SimpleNamespace(flush=AsyncMock())


class TestTheButtonAsks:
    async def test_pressing_reject_does_not_decide_yet(self, wired, session):
        """The item is only rejected once the owner has said why."""
        review, item = wired
        state = _State()
        callback = SimpleNamespace(
            data="", message=_Message(), from_user=SimpleNamespace(id=7),
            answer=AsyncMock(),
        )

        await review.reject_item(
            callback, SimpleNamespace(item_id=item.id), state, session, None
        )

        assert item.status == ContentItemStatus.PENDING_REVIEW
        assert state.state == ReviewStates.waiting_reject_reason

    async def test_the_item_being_rejected_is_remembered(self, wired, session):
        review, item = wired
        state = _State()
        callback = SimpleNamespace(
            data="", message=_Message(), from_user=SimpleNamespace(id=7), answer=AsyncMock()
        )

        await review.reject_item(
            callback, SimpleNamespace(item_id=item.id), state, session, None
        )

        assert state.data.get("reject_item_id") == str(item.id)


class TestTheReasonIsKept:
    async def test_a_typed_reason_lands_on_the_item(self, wired, session):
        review, item = wired
        state = _State()
        state.data["reject_item_id"] = str(item.id)
        message = _Message()
        message.text = "Narx noto'g'ri yozilgan, bizda 690 ming"

        await review.reject_reason(message, state, session, None)

        assert item.status == ContentItemStatus.REJECTED
        assert "690 ming" in item.review_notes
        assert item.reviewed_at is not None
        assert item.reviewed_by == 7
        assert state.state is None

    async def test_skipping_still_rejects(self, wired, session):
        """Forcing a reason would teach owners to type a full stop."""
        review, item = wired
        state = _State()
        state.data["reject_item_id"] = str(item.id)
        message = _Message()
        message.text = "/skip"

        await review.reject_reason(message, state, session, None)

        assert item.status == ContentItemStatus.REJECTED
        assert item.review_notes == ""

    async def test_a_reason_is_not_confused_with_the_planner_note(self, wired, session):
        """`qayta yaratilgani uchun almashtirildi` is the machine's own note."""
        review, item = wired
        state = _State()
        state.data["reject_item_id"] = str(item.id)
        message = _Message()
        message.text = "Rasm juda qorong'i"

        await review.reject_reason(message, state, session, None)

        assert item.review_notes == "Rasm juda qorong'i"

    async def test_an_overlong_reason_is_trimmed(self, wired, session):
        review, item = wired
        state = _State()
        state.data["reject_item_id"] = str(item.id)
        message = _Message()
        message.text = "x" * 5000

        await review.reject_reason(message, state, session, None)

        assert 0 < len(item.review_notes) <= 2000

    async def test_a_lost_state_does_not_crash(self, wired, session):
        review, _ = wired
        state = _State()          # no reject_item_id — the bot restarted
        message = _Message()
        message.text = "sabab"

        await review.reject_reason(message, state, session, None)

        assert state.state is None
        assert message.answers, "the owner is told rather than left waiting"


class TestTheFilterKeepsTheColumnClean:
    """A menu press is navigation, not an opinion about the post."""

    @staticmethod
    def _matches(text: str) -> bool:
        """Would aiogram route this text to the reason handler?"""
        from app.bot.handlers import review

        handler = next(
            h for h in review.router.message.handlers
            if h.callback.__name__ == "reject_reason"
        )
        message = SimpleNamespace(text=text)
        return all(
            f.callback(message) if callable(getattr(f, "callback", None)) else True
            for f in handler.filters
            if getattr(f, "callback", None) is not None
            and not hasattr(f.callback, "state")
        )

    def test_a_menu_button_is_not_a_reason(self):
        from app.bot.keyboards import MENU_TEXTS

        assert MENU_TEXTS, "the guard is only meaningful if there are menu texts"
        assert self._matches(next(iter(MENU_TEXTS))) is False

    def test_skip_reaches_the_handler(self):
        from app.bot.handlers.review import SKIP_COMMAND

        assert self._matches(SKIP_COMMAND) is True

    def test_another_command_is_left_to_its_own_handler(self):
        assert self._matches("/start") is False

    def test_an_ordinary_sentence_is_a_reason(self):
        assert self._matches("Narx noto'g'ri") is True
