"""Leads go to the client's CRM; the CRM's public catalog grounds the bot.

Shanghai School's site posts its enrolment form to `/api/public/register`. A
lead the bot caught goes to the same place, so the sales team has one inbox —
and the same API publishes the course list and branches, which is the most
authoritative thing the bot can quote. Sending is opt-in per business, because
the first push also backfills every lead already in the database.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.services.crm import (
    Catalog,
    CrmConfig,
    CrmError,
    build_payload,
    catalog_context,
    crm_config,
    match_course,
    push_lead,
)

COURSES = [
    {"id": 8, "name": "Xitoy Tili", "duration": "17 oy", "price": None,
     "intensity": "Haftasiga 4.5 soat", "is_active": True, "description": "HSK"},
    {"id": 32, "name": "Xitoy Tili — Ochiq", "duration": "—", "price": None,
     "intensity": None, "is_active": True},
    {"id": 9, "name": "Ingliz Tili", "duration": "17 oy", "price": None,
     "intensity": "Haftasiga 4.5 soat", "is_active": True},
    {"id": 11, "name": "Maktabga Tayyorlov", "duration": "7 oy", "price": "350,000 UZS/oy",
     "intensity": "Haftasiga 4.5 soat", "is_active": True},
    {"id": 36, "name": "Python Backend", "duration": "8 oy", "price": "800 000 UZS/oy",
     "intensity": None, "is_active": True},
    {"id": 99, "name": "Yopilgan kurs", "duration": "1 oy", "price": "1", "is_active": False},
]
BRANCHES = [
    {"id": 12, "name": "1-filial", "address": "Toshkent sh., 1-filial manzili",
     "phone": "+998 93 606 62 26", "working_hours": "Du-Sha 9:00-19:00", "is_active": True},
    {"id": 20, "name": "Markaz", "address": "Angren, Mustaqillik ko'chasi 5",
     "phone": "+998 93 000 00 00", "working_hours": "Du-Sha 9:00-19:00", "is_active": True},
]
CFG = CrmConfig(api_base="https://crm.example/api/public", center_id=4, push=True)


def lead(**kw):
    base = {"id": uuid.uuid4(), "full_name": "Ali Valiyev", "username": "@ali",
            "phone": "+998901234567", "interest": "Xitoy tili narxi qancha?",
            "source": "telegram_message"}
    return SimpleNamespace(**{**base, **kw})


class TestConfig:
    def test_reads_business_settings(self):
        business = SimpleNamespace(settings={"crm": {
            "api_base": "https://crm.example/api/public/", "center_id": 4, "push": True}})
        cfg = crm_config(business)
        assert cfg == CrmConfig(api_base="https://crm.example/api/public", center_id=4, push=True)
        assert cfg.register_url == "https://crm.example/api/public/register"

    def test_push_is_off_unless_asked(self):
        cfg = crm_config(SimpleNamespace(settings={"crm": {"api_base": "https://x/api"}}))
        assert cfg is not None and cfg.push is False

    def test_no_config_is_none(self):
        assert crm_config(SimpleNamespace(settings={})) is None
        assert crm_config(SimpleNamespace(settings=None)) is None

    def test_plain_http_is_refused(self):
        assert crm_config(SimpleNamespace(settings={"crm": {"api_base": "http://x/api"}})) is None


class TestMatchCourse:
    def test_matches_a_language_by_its_first_word(self):
        assert match_course("Xitoy tili narxi qancha?", COURSES) == 8

    def test_prefers_the_regular_course_over_the_open_one(self):
        assert match_course("xitoy tiliga yozilmoqchiman", COURSES) == 8

    def test_matches_a_multi_word_name(self):
        assert match_course("bolamni maktabga tayyorlov kursiga", COURSES) == 11

    def test_ambiguous_text_matches_nothing(self):
        assert match_course("ingliz yoki xitoy tili", COURSES) is None

    def test_unrelated_text_matches_nothing(self):
        assert match_course("manzil qayerda", COURSES) is None

    def test_inactive_courses_are_never_chosen(self):
        assert match_course("yopilgan kurs bormi", COURSES) is None


class TestPayload:
    def test_carries_contact_course_and_where_it_came_from(self):
        payload = build_payload(lead(), CFG, course_id=8)
        assert payload["name"] == "Ali Valiyev"
        assert payload["phone"] == "+998901234567"
        assert payload["course_interest"] == 8
        assert payload["center_id"] == 4
        assert "Telegram" in payload["message"]
        assert "Xitoy tili narxi qancha?" in payload["message"]

    def test_falls_back_to_username_then_a_placeholder(self):
        assert build_payload(lead(full_name=""), CFG, None)["name"] == "@ali"
        assert build_payload(lead(full_name="", username=""), CFG, None)["name"]

    def test_omits_an_unknown_course(self):
        assert "course_interest" not in build_payload(lead(), CFG, None)


class TestPush:
    def client(self, handler) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def test_posts_json_to_register(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"success": True, "data": {"id": 77}})

        async with self.client(handler) as client:
            await push_lead(lead(), CFG, COURSES, client=client)
        assert seen["url"] == "https://crm.example/api/public/register"
        assert seen["body"]["phone"] == "+998901234567"
        assert seen["body"]["course_interest"] == 8

    async def test_a_rejection_raises(self):
        async with self.client(lambda r: httpx.Response(422, json={"detail": "bad"})) as client:
            with pytest.raises(CrmError, match="422"):
                await push_lead(lead(), CFG, COURSES, client=client)

    async def test_success_false_raises(self):
        async with self.client(
            lambda r: httpx.Response(200, json={"success": False, "error": "x"})
        ) as client:
            with pytest.raises(CrmError):
                await push_lead(lead(), CFG, COURSES, client=client)

    async def test_a_lead_without_phone_is_not_sent(self):
        async with self.client(lambda r: pytest.fail("must not be called")) as client:
            with pytest.raises(CrmError, match="phone"):
                await push_lead(lead(phone=""), CFG, COURSES, client=client)


class TestCatalogContext:
    def text(self) -> str:
        return catalog_context(Catalog(courses=COURSES, branches=BRANCHES))

    def test_lists_active_courses_with_their_facts(self):
        text = self.text()
        assert "Python Backend" in text and "800 000 UZS/oy" in text and "8 oy" in text
        assert "Yopilgan kurs" not in text

    def test_a_missing_price_is_said_out_loud(self):
        """Silence is what let the model borrow another course's price."""
        line = next(line for line in self.text().splitlines() if line.startswith("- Xitoy Tili:"))
        assert "narx: saytda yo'q" in line

    def test_missing_hours_are_said_out_loud_too(self):
        line = next(line for line in self.text().splitlines() if line.startswith("- Python Backend:"))
        assert "haftalik soat: saytda yo'q" in line

    def test_a_template_address_is_not_quoted(self):
        text = self.text()
        assert "1-filial manzili" not in text
        assert "+998 93 606 62 26" in text
        assert "Angren, Mustaqillik ko'chasi 5" in text

    def test_empty_catalog_is_empty(self):
        assert catalog_context(Catalog(courses=[], branches=[])) == ""
