"""The persistent keyboard, checked against aiogram's own filter resolution.

Every label sits under every prompt, so a button press arrives as ordinary
text while some handler is waiting for ordinary text. Before this was fixed,
pressing "📊 Holat" during `/quick` filed "📊 Holat" as the post's topic — and
because a few buttons happened to be registered earlier than the flows that
would have eaten them, the menu looked like it worked.

These tests resolve real `Message` objects through the real router, so they
fail if a new button is added without a handler, or a new stateful text
handler is added without the menu guard.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from aiogram.types import Chat, Message, User

from app.bot.handlers import build_router
from app.bot.keyboards import MENU_TEXTS, main_menu
from app.bot.states import (
    ClipStates,
    OnboardingStates,
    QuickPostStates,
    ReviewStates,
)

USER = User(id=955631798, is_bot=False, first_name="D")
CHAT = Chat(id=955631798, type="private")

#: Every flow that waits on free text, and so could swallow a button.
TEXT_HUNGRY_STATES = [
    QuickPostStates.waiting_topic.state,
    ClipStates.waiting_topic.state,
    OnboardingStates.waiting_answer.state,
    OnboardingStates.waiting_business_name.state,
    ReviewStates.waiting_edit_instruction.state,
    ReviewStates.waiting_new_datetime.state,
]


async def resolve(text: str, raw_state: str | None) -> str | None:
    """Which handler aiogram would run for this text in this state."""
    message = Message(message_id=1, date=datetime.now(), chat=CHAT, from_user=USER, text=text)
    data = {"raw_state": raw_state, "event_from_user": USER, "bot": None}

    async def walk(router) -> str | None:
        for handler in router.message.handlers:
            matched, _ = await handler.check(message, **data)
            if matched:
                return handler.callback.__name__
        for sub in router.sub_routers:
            if found := await walk(sub):
                return found
        return None

    return await walk(build_router())


class TestEveryButtonReachesAHandler:
    @pytest.mark.parametrize("label", sorted(MENU_TEXTS))
    async def test_a_button_resolves_when_idle(self, label: str):
        assert await resolve(label, None) is not None, label

    @pytest.mark.parametrize("label", sorted(MENU_TEXTS))
    @pytest.mark.parametrize("state", TEXT_HUNGRY_STATES)
    async def test_a_flow_waiting_on_text_does_not_swallow_it(self, label: str, state: str):
        """The whole point: the button behaves the same mid-flow as it does idle."""
        assert await resolve(label, state) == await resolve(label, None), (label, state)


class TestOrdinaryTextStillReachesTheFlow:
    """The guard must exclude button labels — and nothing else."""

    async def test_a_real_topic_is_still_accepted(self):
        assert await resolve("Sentabr qabuli haqida post", QuickPostStates.waiting_topic.state) is not None

    async def test_a_topic_is_not_answered_by_a_menu_handler(self):
        handler = await resolve("Sentabr qabuli", QuickPostStates.waiting_topic.state)
        assert handler == "quick_topic"

    async def test_an_onboarding_answer_still_lands(self):
        handler = await resolve("Bizda 12 kishilik guruhlar", OnboardingStates.waiting_answer.state)
        assert handler == "handle_answer"


class TestMenuTextsStayInSync:
    def test_the_list_is_derived_from_the_keyboard(self):
        """Hardcoding it would let a new button be forgotten and swallowed."""
        on_keyboard = {b.text for row in main_menu().keyboard for b in row}
        assert on_keyboard == MENU_TEXTS
