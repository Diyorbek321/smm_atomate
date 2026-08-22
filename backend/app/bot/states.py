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


class QuickPostStates(StatesGroup):
    waiting_topic = State()


class LeadStates(StatesGroup):
    """A stranger wrote in from a post CTA — capture them as a lead."""

    waiting_interest = State()
    waiting_phone = State()
