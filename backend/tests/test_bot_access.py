"""Who the bot lets in, and to which business.

The bot is public on purpose — that is where leads arrive — so the entry
points have to distinguish three kinds of sender: an operator who may create a
business, a member who may operate the ones they belong to, and a stranger who
is a prospect and nothing else.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.bot.handlers.onboarding import _resolve_business_id
from app.bot.middlewares import AdminContextMiddleware
from app.models.business import BusinessAdmin


def user(uid: int) -> SimpleNamespace:
    return SimpleNamespace(id=uid)


def membership(business_id: uuid.UUID) -> BusinessAdmin:
    return BusinessAdmin(business_id=business_id, telegram_user_id=1, role="owner")


class FakeState:
    """The FSM state is client-held storage, which is the whole point."""

    def __init__(self, **data):
        self._data = data

    async def get_data(self):
        return self._data


class TestRegistrationAllowlist:
    def test_an_empty_allowlist_keeps_the_bot_open(self, monkeypatch):
        """Local development and the test suite rely on this."""
        monkeypatch.setattr("app.core.config.settings.telegram_admin_ids", "", raising=False)
        assert AdminContextMiddleware._may_register(user(12345)) is True

    def test_only_listed_accounts_may_create_a_business(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.config.settings.telegram_admin_ids", "955631798", raising=False
        )
        assert AdminContextMiddleware._may_register(user(955631798)) is True
        assert AdminContextMiddleware._may_register(user(12345)) is False

    def test_several_ids_are_accepted(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.config.settings.telegram_admin_ids", "111, 222 ,333", raising=False
        )
        for uid in (111, 222, 333):
            assert AdminContextMiddleware._may_register(user(uid)) is True
        assert AdminContextMiddleware._may_register(user(444)) is False

    def test_an_anonymous_update_may_not_register(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.telegram_admin_ids", "111", raising=False)
        assert AdminContextMiddleware._may_register(None) is False


class TestActiveBusinessResolution:
    """`active_business_id` lives in FSM state, so it is a claim, not a fact."""

    async def test_a_stored_id_the_sender_administers_is_used(self):
        mine = uuid.uuid4()
        admins = [membership(mine)]
        resolved = await _resolve_business_id(
            FakeState(active_business_id=str(mine)), admins[0], admins
        )
        assert resolved == str(mine)

    async def test_a_foreign_stored_id_falls_back_to_the_sender_s_own(self):
        mine, theirs = uuid.uuid4(), uuid.uuid4()
        admins = [membership(mine)]
        resolved = await _resolve_business_id(
            FakeState(active_business_id=str(theirs)), admins[0], admins
        )
        assert resolved == str(mine)
        assert resolved != str(theirs)

    async def test_a_sender_with_no_membership_gets_nothing(self):
        resolved = await _resolve_business_id(FakeState(), None, [])
        assert resolved is None

    async def test_a_business_created_this_moment_is_still_usable(self):
        """Its membership row exists but was written after `admins` resolved."""
        fresh = uuid.uuid4()
        resolved = await _resolve_business_id(
            FakeState(active_business_id=str(fresh)), None, []
        )
        assert resolved == str(fresh)

    async def test_no_stored_id_uses_the_active_membership(self):
        mine = uuid.uuid4()
        admins = [membership(mine)]
        assert await _resolve_business_id(FakeState(), admins[0], admins) == str(mine)


@pytest.mark.parametrize("raw", ["", "   ", "not-a-number", "12a"])
def test_junk_in_the_allowlist_is_ignored(monkeypatch, raw: str):
    """A typo in .env must not silently lock the owner out of their own bot."""
    monkeypatch.setattr("app.core.config.settings.telegram_admin_ids", raw, raising=False)
    assert AdminContextMiddleware._may_register(user(999)) is True
