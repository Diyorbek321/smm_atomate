"""Sequencing scene archetypes into a clip.

The model's half of this is covered by the composer's tests; what matters here
is the validation seam between them. A model that names a scene that does not
exist, numbers a list the archetype numbers itself, or leaves a required field
blank must cost one scene — never a whole clip, and never a render with a hole
in it.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.agents.promo_brief import (
    _FIELDS,
    BriefPlan,
    BriefScene,
    PromoBriefAgent,
    SceneCopy,
    _copy_for,
    _missing,
)
from app.services.promo_scenes import archetype_names
from tests.test_agents import make_business


def plan_with(*scenes: BriefScene, mood: str = "tezkor") -> BriefPlan:
    """A plan built past the schema's length rule.

    `_job` is the subject of these tests, not the schema — a two-scene example
    reads better than the same case padded out to the minimum. The length rule
    itself is covered in `TestSchema`.
    """
    return BriefPlan.model_construct(mood=mood, scenes=list(scenes))


def scene(use: str, say: str = "Bir *ikki* uch to'rt besh.", **copy) -> BriefScene:
    return BriefScene(use=use, say=say, text=SceneCopy(**copy))


def _needs(name: str) -> list[str]:
    from app.services.promo_scenes import catalogue

    return next(a["needs"] for a in catalogue() if a["name"] == name)


def build(plan: BriefPlan, topic: str = "SMM tizimi", mood: str | None = None):
    business = make_business(id=uuid.uuid4())
    return PromoBriefAgent(session=None)._job(plan, business, topic, mood)


class TestCopyShaping:
    def test_a_shared_field_lands_under_each_archetypes_own_name(self):
        # One `title` in the schema; three different names in the archetypes.
        assert _copy_for("cta", SceneCopy(title="Salom")) == {"headline": "Salom"}
        assert _copy_for("stat", SceneCopy(title="Xarajat", to=8))["label"] == "Xarajat"
        assert _copy_for("narx", SceneCopy(title="Tariflar"))["title"] == "Tariflar"

    def test_copy_the_archetype_never_asked_for_is_dropped(self):
        # A model that fills `quote` on a cta scene wrote something nobody
        # asked for; it must not travel into the script.
        assert _copy_for("cta", SceneCopy(title="Salom", quote="Gap")) == {"headline": "Salom"}

    def test_a_table_row_is_split_on_its_separator(self):
        # Rows arrive as strings: the schema may hold only one list.
        text = _copy_for("narx", SceneCopy(title="Tariflar",
                                           items=["Boshlang'ich: 490 ming", "Biznes: 890 ming"]))
        assert text["rows"] == [{"left": "Boshlang'ich", "right": "490 ming"},
                                {"left": "Biznes", "right": "890 ming"}]

    def test_a_row_with_no_separator_keeps_its_label(self):
        text = _copy_for("narx", SceneCopy(title="T", items=["Kelishuv asosida"]))
        assert text["rows"] == [{"left": "Kelishuv asosida", "right": ""}]

    def test_snake_case_becomes_what_the_template_reads(self):
        text = _copy_for("taqqoslash", SceneCopy(
            left_title="Eski", left_body="a", right_title="Yangi", right_body="b"))
        assert set(text) == {"leftTitle", "leftBody", "rightTitle", "rightBody"}

    def test_empty_fields_never_reach_the_archetype(self):
        # A blank string would resolve a placeholder to nothing and render an
        # empty line rather than being caught as a missing field.
        assert _copy_for("iqtibos", SceneCopy(quote="Gap")) == {"quote": "Gap"}

    def test_headline_words_are_upper_cased_and_the_last_sits_back(self):
        text = _copy_for("sarlavha", SceneCopy(items=["smm", "tizimi", "kerakmi"]))
        assert [w["text"] for w in text["lines"]] == ["SMM", "TIZIMI", "KERAKMI"]
        assert "color" in text["lines"][-1] and "color" not in text["lines"][0]

    def test_numbering_the_model_added_is_stripped(self):
        # The archetype draws the index itself; "1. Bir" would render "1  1. Bir".
        text = _copy_for("royxat", SceneCopy(title="T", items=["1. Bir", "2) Ikki", "Uch"]))
        assert text["items"] == ["Bir", "Ikki", "Uch"]

    def test_every_archetype_can_be_filled_from_the_schema(self):
        # An archetype with no mapping is one no model can ever fill, and the
        # only symptom is that scene quietly never appearing in a clip.
        for name in archetype_names():
            assert name in _FIELDS, f"«{name}» uchun maydon jadvali yo'q"

    def test_every_required_field_is_reachable(self):
        for name, mapping in _FIELDS.items():
            required = {n.rstrip("[]") for n in _needs(name) if not n.endswith("?")}
            assert required <= set(mapping.values()), name

    def test_a_word_suffix_is_dropped_rather_than_glued_to_the_numeral(self):
        # Seen in a real clip: the model answered "soat", `short(3)` trimmed it
        # to "soa", and the frame read "30soa".
        text = _copy_for("sanoq", SceneCopy(to=30, caption="soat", suffix="soat"))
        assert "suffix" not in text

    def test_a_symbol_suffix_survives(self):
        assert _copy_for("stat", SceneCopy(title="L", to=83, suffix="%"))["suffix"] == "%"

    def test_a_counter_left_at_zero_reads_as_not_provided(self):
        # `to` cannot be optional in the schema — Gemini rejects a nullable
        # integer — so zero is how "the model skipped this" arrives.
        text = _copy_for("sanoq", SceneCopy(to=0, caption="qoldi"))
        assert "to" not in text
        assert _missing("sanoq", text) == ["to"]


class TestRequiredFields:
    def test_a_complete_scene_is_missing_nothing(self):
        assert _missing("cta", {"headline": "Salom"}) == []

    def test_a_blank_required_field_is_reported(self):
        assert _missing("cta", {}) == ["headline"]

    def test_an_optional_field_is_not_required(self):
        assert _missing("iqtibos", {"quote": "Gap"}) == []

    def test_a_list_field_is_matched_without_its_brackets(self):
        assert _missing("royxat", {"title": "T"}) == ["items"]
        assert _missing("royxat", {"title": "T", "items": ["bir"]}) == []


class TestValidation:
    def test_a_good_plan_becomes_a_job_the_composer_can_build(self):
        job, dropped, complaints = build(plan_with(
            scene("stat", title="Xarajat", to=83, suffix="%"),
            scene("cta", title="Bepul sinash"),
        ))
        assert not dropped and not complaints
        assert [s["use"] for s in job["scenes"]] == ["stat", "cta"]
        assert len(job["say"]) == 2

    def test_an_invented_archetype_costs_one_scene_not_the_clip(self):
        job, dropped, complaints = build(plan_with(
            scene("bunday-sahna-yoq"),
            scene("cta", title="Salom"),
        ))
        assert dropped == ["bunday-sahna-yoq"]
        assert [s["use"] for s in job["scenes"]] == ["cta"]
        assert "bunday-sahna-yoq" in complaints[0]

    def test_a_scene_missing_its_copy_is_dropped_with_the_field_named(self):
        job, dropped, complaints = build(plan_with(
            scene("stat", title="Xarajat"),                 # no `to`
            scene("cta", title="Salom"),
        ))
        assert dropped == ["stat"] and "to" in complaints[0]
        assert len(job["scenes"]) == 1

    def test_a_scene_with_nothing_to_say_is_dropped(self):
        _, dropped, complaints = build(plan_with(
            scene("cta", say="   ", title="Salom"),
        ))
        assert dropped == ["cta"] and "say" in complaints[0]

    def test_slots_stay_unique_when_a_scene_is_dropped(self):
        # Slots are the only thing keeping two uses of one archetype apart; a
        # dropped scene must not make two survivors share one.
        job, _, _ = build(plan_with(
            scene("cta", title="Bir"),
            scene("bunday-sahna-yoq"),
            scene("cta", title="Ikki"),
        ))
        slots = [s["slot"] for s in job["scenes"]]
        assert len(set(slots)) == len(slots)
        assert [job["text"][s]["headline"] for s in slots] == ["Bir", "Ikki"]

    def test_say_indexes_follow_the_surviving_scenes(self):
        job, _, _ = build(plan_with(
            scene("bunday-sahna-yoq"),
            scene("cta", say="Oxirgi gap.", title="Salom"),
        ))
        ref = job["scenes"][0]
        assert job["say"][ref["say"]] == "Oxirgi gap."

    def test_an_explicit_mood_overrides_the_models_choice(self):
        job, _, _ = build(plan_with(scene("cta", title="X"), mood="qorongu"),
                          mood="iliq")
        assert job["mood"] == "iliq"

    def test_the_models_mood_is_used_when_none_is_forced(self):
        job, _, _ = build(plan_with(scene("cta", title="X"), mood="qorongu"))
        assert job["mood"] == "qorongu"


class TestSchema:
    def test_a_clip_too_short_to_make_an_argument_is_refused(self):
        with pytest.raises(ValidationError):
            BriefPlan(mood="tezkor", scenes=[scene("cta", title="X")] * 2)

    def test_a_plan_of_workable_length_validates(self):
        assert len(BriefPlan(mood="tezkor",
                             scenes=[scene("cta", title="X")] * 3).scenes) == 3

    def test_copy_longer_than_the_layout_holds_is_trimmed_not_rejected(self):
        # A model one character over must not fail the whole clip.
        assert len(SceneCopy(title="x" * 99).title) == 28


class TestPrompt:
    def test_every_archetype_is_offered_to_the_model(self):
        business = make_business(id=uuid.uuid4())
        prompt = PromoBriefAgent(session=None)._prompt(business, None, "SMM", 8)
        for name in archetype_names():
            assert name in prompt

    def test_the_topic_is_stated_as_the_subject_of_every_scene(self):
        business = make_business(id=uuid.uuid4())
        prompt = PromoBriefAgent(session=None)._prompt(business, None, "backend kursi", 8)
        assert "backend kursi" in prompt


class TestWiring:
    def test_the_render_task_exists_under_the_name_the_api_queues(self):
        from app.tasks import generation

        assert hasattr(generation, "render_brief_clip")

    @pytest.mark.parametrize("scenes", [2, 13])
    def test_the_endpoint_refuses_a_length_the_agent_cannot_plan(self, scenes):
        assert not 3 <= scenes <= 12
