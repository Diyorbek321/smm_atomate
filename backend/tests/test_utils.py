"""Unit tests for the pure helper layer."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.utils.dates import iso_week, slot_to_datetime, spread_slots, week_bounds
from app.utils.json_tools import extract_json, to_gemini_schema
from app.utils.text import (
    append_block,
    find_placeholders,
    find_robotic_phrases,
    normalize_hashtags,
    slugify,
    truncate_caption,
)


class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_block(self):
        assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}

    def test_surrounded_by_prose(self):
        raw = 'Mana javob:\n{"topic": "IELTS"}\nRahmat!'
        assert extract_json(raw) == {"topic": "IELTS"}

    def test_trailing_comma_is_repaired(self):
        assert extract_json('{"a": 1,}') == {"a": 1}

    def test_array_payload(self):
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            extract_json("not json at all")


class TestGeminiSchema:
    def test_pydantic_model_is_flattened(self):
        from app.schemas.content import StrategyOutput

        schema = to_gemini_schema(StrategyOutput)
        assert schema["type"] == "object"
        assert "slots" in schema["properties"]
        # $defs must be inlined, not referenced.
        assert "$defs" not in schema
        assert "$ref" not in str(schema)

    def test_optional_union_collapses_to_concrete_type(self):
        from app.schemas.knowledge_base import KnowledgeExtraction

        schema = to_gemini_schema(KnowledgeExtraction)
        assert schema["properties"]["phone"]["type"] == "string"
        assert "anyOf" not in str(schema)


class TestTextHelpers:
    def test_hashtags_are_deduped_and_prefixed(self):
        tags = normalize_hashtags(["ielts", "#IELTS", "toshkent ", "", "#toshkent"])
        assert tags == ["#ielts", "#toshkent"]

    def test_hashtag_limit(self):
        assert len(normalize_hashtags([f"tag{i}" for i in range(50)])) == 30

    def test_placeholders_detected(self):
        assert find_placeholders("Narx: [narx] so'm") == ["[narx]"]
        assert find_placeholders("Salom {{name}}") == ["{{name}}"]
        assert find_placeholders("Narx 600 000 so'm") == []

    def test_robotic_phrases_detected(self):
        assert find_robotic_phrases("Albatta! Mana sizga post")
        assert not find_robotic_phrases("IELTS 7.0 olish qiyin emas.")

    def test_truncate_prefers_word_boundary(self):
        text = "Bir ikki uch to'rt besh olti yetti sakkiz to'qqiz o'n"
        result = truncate_caption(text, 25)
        assert len(result) <= 25
        assert result.endswith("…")

    def test_truncate_noop_when_short(self):
        assert truncate_caption("qisqa", 100) == "qisqa"

    def test_append_block_is_idempotent(self):
        text = append_block("Post matni", "📞 +998901234567")
        assert append_block(text, "📞 +998901234567") == text

    def test_slugify(self):
        assert slugify("Yangi O'quv Markazi!") == "yangi-o-quv-markazi"


class TestDates:
    def test_week_bounds_monday_to_sunday(self):
        start, end = week_bounds(date(2026, 8, 20))   # Thursday
        assert start == date(2026, 8, 17)
        assert end == date(2026, 8, 23)

    def test_slot_to_datetime_is_utc(self):
        when = slot_to_datetime(date(2026, 8, 17), 1, 18, "Asia/Tashkent")
        assert when.tzinfo == UTC
        # Tashkent is UTC+5 → 18:00 local is 13:00 UTC.
        assert when.hour == 13
        assert when.date() == date(2026, 8, 18)

    def test_spread_slots_count_and_order(self):
        slots = spread_slots(date(2026, 8, 17), 8, [9, 13, 18], horizon_days=7, tz_name="Asia/Tashkent")
        assert len(slots) == 8
        assert slots == sorted(slots)

    def test_spread_slots_empty(self):
        assert spread_slots(date(2026, 8, 17), 0, [9]) == []

    def test_iso_week(self):
        year, week = iso_week(date(2026, 1, 1))
        assert isinstance(year, int) and 1 <= week <= 53


class TestBotDatetimeParsing:
    def test_time_only_rolls_forward(self):
        from app.bot.utils import parse_datetime

        result = parse_datetime("18:00", "Asia/Tashkent")
        assert result is not None
        assert result.tzinfo is not None
        assert result > datetime.now(UTC)

    def test_full_date(self):
        from app.bot.utils import parse_datetime

        result = parse_datetime("25.12.2030 09:30", "Asia/Tashkent")
        assert result is not None
        assert result.year == 2030 and result.month == 12

    def test_garbage_returns_none(self):
        from app.bot.utils import parse_datetime

        assert parse_datetime("ertaga kechqurun", "Asia/Tashkent") is None


class TestAppendBlockDeduplication:
    """The copywriter often already wrote the contacts into the caption."""

    def test_exact_repeat_is_skipped(self):
        block = "📞 +998 90 123 45 67\n✍️ @bright_ielts"
        text = append_block("Post matni", block)
        assert append_block(text, block) == text

    def test_inline_contacts_are_not_repeated(self):
        # Model wrote them space-separated; our block is newline-separated.
        caption = "IELTS kursi boshlanmoqda. 📞 +998 90 123 45 67 ✍️ @bright_ielts 📍 Chilonzor"
        block = "📞 +998 90 123 45 67\n✍️ @bright_ielts\n📍 Chilonzor"
        assert append_block(caption, block) == caption

    def test_partially_present_block_is_still_appended(self):
        caption = "IELTS kursi. 📞 +998 90 123 45 67"
        block = "📞 +998 90 123 45 67\n✍️ @bright_ielts"
        result = append_block(caption, block)
        assert result != caption
        assert "@bright_ielts" in result

    def test_case_and_spacing_differences_still_match(self):
        caption = "Yozilish uchun   QO'NG'IROQ qiling"
        assert append_block(caption, "Qo'ng'iroq qiling") == caption

    def test_empty_inputs(self):
        assert append_block("", "blok") == "blok"
        assert append_block("matn", "") == "matn"


class TestSchemaPropertyNames:
    """A field literally named `description` must survive schema conversion.

    Gemini rejected the whole request when the converter mistook the property
    name for the JSON Schema keyword and stringified the nested schema.
    """

    def _offering_props(self, schema: dict) -> dict:
        return schema["properties"]["key_offerings"]["items"]["properties"]

    def test_gemini_schema_keeps_description_as_a_field(self):
        from app.schemas.knowledge_base import KnowledgeExtraction
        from app.utils.json_tools import to_gemini_schema

        props = self._offering_props(to_gemini_schema(KnowledgeExtraction))
        assert props["description"] == {"type": "string"}

    def test_openai_schema_keeps_description_as_a_field(self):
        from app.schemas.knowledge_base import KnowledgeExtraction
        from app.utils.json_tools import to_openai_schema

        props = self._offering_props(to_openai_schema(KnowledgeExtraction))
        assert props["description"]["type"] == "string"

    def test_optional_fields_are_marked_nullable_for_gemini(self):
        from app.schemas.knowledge_base import KnowledgeExtraction
        from app.utils.json_tools import to_gemini_schema

        props = self._offering_props(to_gemini_schema(KnowledgeExtraction))
        assert props["duration"]["nullable"] is True

    def test_a_real_docstring_is_still_kept(self):
        from app.schemas.content import PlanSlot
        from app.utils.json_tools import to_gemini_schema

        schema = to_gemini_schema(PlanSlot)
        assert isinstance(schema.get("description"), str)

    def test_every_agent_schema_converts_without_stringified_nodes(self):
        import json

        from app.schemas.content import CopyOutput, EditorOutput, StrategyOutput, VoiceInstruction
        from app.schemas.knowledge_base import KnowledgeExtraction
        from app.utils.json_tools import to_gemini_schema, to_openai_schema

        for model in (CopyOutput, EditorOutput, StrategyOutput, VoiceInstruction, KnowledgeExtraction):
            for converter in (to_gemini_schema, to_openai_schema):
                schema = converter(model)
                # A stringified sub-schema shows up as "{'type': 'string'}".
                assert "{'type'" not in json.dumps(schema), f"{model.__name__} via {converter.__name__}"


class TestLLMSchemaExpressiveness:
    def test_strict_copy_schema_carries_slide_fields(self):
        """dict[str, Any] fields degrade to a dummy {"value": str} in the Gemini
        schema — generation must use the strict variant that keeps real fields."""
        from app.schemas.content import CopyOutputStrict
        from app.utils.json_tools import to_gemini_schema

        schema = to_gemini_schema(CopyOutputStrict)
        slide_props = schema["properties"]["slides"]["items"]["properties"]
        assert {"index", "title", "body", "bullets"} <= set(slide_props)
        quiz_props = schema["properties"]["quiz"]["properties"]
        assert {"question", "answers", "correct_option_id"} <= set(quiz_props)

    def test_strict_output_converts_to_loose_copy(self):
        from app.schemas.content import CarouselSlideSpec, CopyOutputStrict

        strict = CopyOutputStrict(
            caption_tg="matn", slides=[CarouselSlideSpec(index=1, title="Xato 1", body="Yechim")]
        )
        copy = strict.to_copy_output()
        assert copy.slides[0]["title"] == "Xato 1"  # dicts, downstream .get() works
        assert copy.quiz == {} and copy.script == {}


class TestDedupePhone:
    """The same number twice in one caption reads as careless."""

    PHONE = "+998931913308"

    def test_the_first_mention_survives(self):
        from app.utils.text import dedupe_phone

        caption = "Salom\n\n📍 Angren\n📞 +998931913308\n\nQo'ng'iroq qiling: +998931913308"
        result = dedupe_phone(caption, self.PHONE)
        assert result.count("931913308") == 1
        assert "📞 +998931913308" in result

    def test_the_wording_around_a_dropped_number_is_kept(self):
        from app.utils.text import dedupe_phone

        caption = "📞 +998931913308\nYozilish uchun qo'ng'iroq qiling: +998931913308"
        assert dedupe_phone(caption, self.PHONE).endswith("Yozilish uchun qo'ng'iroq qiling")

    def test_a_bare_repeat_line_is_dropped_entirely(self):
        from app.utils.text import dedupe_phone

        assert dedupe_phone("📞 +998931913308\n📞 +998931913308", self.PHONE) == "📞 +998931913308"

    def test_a_single_mention_is_untouched(self):
        from app.utils.text import dedupe_phone

        caption = "Bir marta: +998931913308"
        assert dedupe_phone(caption, self.PHONE) == caption

    def test_punctuation_variants_still_match(self):
        from app.utils.text import dedupe_phone

        caption = "Telefon 93 191-33-08\nYana +998 93 191 33 08 ga yozing"
        result = dedupe_phone(caption, self.PHONE)
        assert result == "Telefon 93 191-33-08\nYana ga yozing"

    def test_a_stranded_colon_is_removed(self):
        """"Qo'ng'iroq qiling: 🎓" reads worse than no colon at all."""
        from app.utils.text import dedupe_phone

        caption = "📞 +998931913308\nYozilish uchun qo'ng'iroq qiling: +998931913308 🎓"
        assert dedupe_phone(caption, self.PHONE).endswith("qo'ng'iroq qiling 🎓")

    def test_a_meaningful_colon_survives(self):
        from app.utils.text import dedupe_phone

        caption = "📞 +998931913308\n📌 Narxlar: +998931913308 — Til kurslari 350 000"
        assert "Narxlar: — Til kurslari" in dedupe_phone(caption, self.PHONE)

    def test_a_different_number_is_left_alone(self):
        from app.utils.text import dedupe_phone

        caption = "+998931913308 yoki +998901112233"
        assert dedupe_phone(caption, self.PHONE) == caption

    def test_no_phone_configured_changes_nothing(self):
        from app.utils.text import dedupe_phone

        caption = "+998931913308 va yana +998931913308"
        assert dedupe_phone(caption, "") == caption

    def test_empty_caption(self):
        from app.utils.text import dedupe_phone

        assert dedupe_phone("", self.PHONE) == ""
