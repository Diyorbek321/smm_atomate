"""FSM state groups for the bot conversations."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    """Knowledge-base interview."""

    waiting_business_name = State()
    waiting_answer = State()


class ReviewStates(StatesGroup):
    """Editing a generated post."""

    waiting_edit_instruction = State()
    waiting_new_datetime = State()
    #: Why the owner is throwing this one away. The only route their taste has
    #: into the system, and the button used to discard it.
    waiting_reject_reason = State()


class QuickPostStates(StatesGroup):
    waiting_topic = State()


class LeadStates(StatesGroup):
    """A stranger wrote in from a post CTA — capture them as a lead."""

    waiting_interest = State()
    waiting_phone = State()


class ClipStates(StatesGroup):
    """Asking what a promo clip should be about."""

    waiting_topic = State()


class FootageStates(StatesGroup):
    """Collecting real clips for the footage shelf.

    A separate state because the same video message means two different things:
    outside it the owner wants *this* clip edited into a post, inside it they
    are stocking the library future clips are built from.
    """

    waiting_clips = State()
