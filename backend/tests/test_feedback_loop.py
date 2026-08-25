"""What happens after a post goes out, and how it reaches the next plan.

Before this the system could plan, write, render and publish, but never learn:
nothing that happened after publishing came back. These lock the loop shut.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.strategist import StrategyRequest, _performance_block


class TestPerformanceBlock:
    """How last month's numbers are put in front of the planner."""

    SAMPLE = {
        "published": 14,
        "by_pillar": {
            "sales": {"posts": 5, "reactions": 20, "measured": 5, "avg_reactions": 4.0},
            "educational": {"posts": 6, "reactions": 72, "measured": 6, "avg_reactions": 12.0},
            "interactive": {"posts": 3, "reactions": 0, "measured": 0, "avg_reactions": None},
        },
        "recent_topics": ["IELTS 4 mezon", "ARE formulasi"],
    }

    def test_a_business_with_nothing_published_gets_no_block(self):
        """Inventing a track record for a new account is worse than silence."""
        assert _performance_block({}) == ""
        assert _performance_block({"published": 0, "by_pillar": {}}) == ""

    def test_pillars_are_ranked_by_response(self):
        block = _performance_block(self.SAMPLE)
        assert block.index("educational") < block.index("sales")

    def test_an_unmeasured_pillar_is_not_ranked_as_zero(self):
        """No reactions recorded and no reactions received are different facts."""
        block = _performance_block(self.SAMPLE)
        assert "o'lchanmagan" in block
        assert block.index("sales") < block.index("interactive")

    def test_the_winning_pillar_is_named_but_the_mix_is_not_touched(self):
        """Pillar shares are a strategy decision, not a popularity contest."""
        block = _performance_block(self.SAMPLE)
        assert "educational" in block
        assert "Ulushni o'zgartirma" in block

    def test_recent_topics_are_listed_so_the_plan_stops_repeating_them(self):
        block = _performance_block(self.SAMPLE)
        assert "ARE formulasi" in block
        assert "takrorlama" in block

    def test_a_single_pillar_gets_no_winner_line(self):
        block = _performance_block({
            "published": 2,
            "by_pillar": {"sales": {"posts": 2, "reactions": 4, "measured": 2, "avg_reactions": 2.0}},
            "recent_topics": [],
        })
        assert "Eng ko'p javob bergan" not in block

    def test_the_request_defaults_to_no_history(self):
        request = StrategyRequest(business=object(), knowledge=None,
                                  starts_on=__import__("datetime").date(2026, 9, 1))
        assert request.performance == {}


class TestReactionCapture:
    """Telegram pushes reaction totals; they have to land on the right item."""

    @staticmethod
    def _event(message_id: int, reactions, *, chat_id: int = -1001, username: str = "kanal"):
        # A real MessageReactionCountUpdated always carries the chat; the
        # handler needs it to tell one client's channel from another's.
        return SimpleNamespace(
            message_id=message_id,
            reactions=reactions,
            chat=SimpleNamespace(id=chat_id, username=username),
        )

    @staticmethod
    def _reaction(emoji: str, total: int):
        return SimpleNamespace(type=SimpleNamespace(emoji=emoji), total_count=total)

    async def _run(self, monkeypatch, item, event, *, owner=None):
        from app.bot.handlers import reactions as handler

        self.repo = SimpleNamespace(by_telegram_message=AsyncMock(return_value=item))
        creds = SimpleNamespace(business_for_channel=AsyncMock(return_value=owner))
        monkeypatch.setattr(handler, "ContentItemRepository", lambda session: self.repo)
        monkeypatch.setattr(handler, "CredentialsRepository", lambda session: creds)
        session = SimpleNamespace(flush=AsyncMock())
        await handler.record_reactions(event, session)
        return session

    @pytest.mark.asyncio
    async def test_the_lookup_is_scoped_to_the_channel_that_fired(self, monkeypatch):
        """A message id repeats across channels, so the id alone is not enough."""
        owner = uuid.uuid4()
        item = SimpleNamespace(id=uuid.uuid4(), metrics={})
        await self._run(monkeypatch, item, self._event(9, [self._reaction("👍", 1)]), owner=owner)

        self.repo.by_telegram_message.assert_awaited_once_with("9", business_id=owner)

    @pytest.mark.asyncio
    async def test_an_unknown_channel_still_looks_up_without_a_scope(self, monkeypatch):
        """Better a best-effort match than dropping the only signal we get."""
        item = SimpleNamespace(id=uuid.uuid4(), metrics={})
        await self._run(monkeypatch, item, self._event(9, [self._reaction("👍", 1)]), owner=None)

        self.repo.by_telegram_message.assert_awaited_once_with("9", business_id=None)

    @pytest.mark.asyncio
    async def test_totals_and_breakdown_are_stored(self, monkeypatch):
        item = SimpleNamespace(id=uuid.uuid4(), metrics={})
        await self._run(monkeypatch, item,
                        self._event(41, [self._reaction("👍", 7), self._reaction("🔥", 3)]))
        assert item.metrics["reactions"] == 10
        assert item.metrics["reaction_breakdown"] == {"👍": 7, "🔥": 3}
        assert item.metrics["measured_at"]

    @pytest.mark.asyncio
    async def test_a_later_update_replaces_rather_than_accumulates(self, monkeypatch):
        """The event carries running totals, not a delta."""
        item = SimpleNamespace(id=uuid.uuid4(), metrics={"reactions": 99})
        await self._run(monkeypatch, item, self._event(41, [self._reaction("👍", 2)]))
        assert item.metrics["reactions"] == 2

    @pytest.mark.asyncio
    async def test_other_metrics_on_the_item_survive(self, monkeypatch):
        item = SimpleNamespace(id=uuid.uuid4(), metrics={"leads": 3})
        await self._run(monkeypatch, item, self._event(41, [self._reaction("👍", 1)]))
        assert item.metrics["leads"] == 3

    @pytest.mark.asyncio
    async def test_a_message_we_did_not_post_is_ignored(self, monkeypatch):
        """Channels carry hand-written posts too; they match no item."""
        session = await self._run(monkeypatch, None, self._event(999, []))
        session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_post_with_reactions_removed_records_zero(self, monkeypatch):
        item = SimpleNamespace(id=uuid.uuid4(), metrics={"reactions": 5})
        await self._run(monkeypatch, item, self._event(41, []))
        assert item.metrics["reactions"] == 0


class TestReactionUpdatesAreSubscribed:
    def test_the_bot_asks_telegram_for_reaction_updates(self):
        """A handler nobody receives events for is dead code."""
        from aiogram import Dispatcher

        from app.bot.handlers import build_router

        dispatcher = Dispatcher()
        dispatcher.include_router(build_router())
        assert "message_reaction_count" in dispatcher.resolve_used_update_types()
