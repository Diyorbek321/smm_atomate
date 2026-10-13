"""Script first, voice second — the flow owning your own narration requires.

`render_brief_clip` wrote, voiced and rendered a clip inside one call, so the
script existed only between two lines of code. Reading it yourself means seeing
it, which means the plan has to outlive the request that produced it.

The pending plan is a file rather than an FSM state on purpose: the worker that
produces the script cannot reach the owner's FSM, a state set optimistically
before the model answered would strand anyone whose plan failed, and a file
survives a restart.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from app.services import clip_plans


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(clip_plans, "_root", lambda: tmp_path / "plans")


def a_job(lines=("Bir gap.", "Ikkinchi gap.")):
    return {"name": "x", "say": list(lines), "scenes": [], "text": {}}


def a_shape():
    return {"skeleton": "fakt", "opening": "yolg'iz jumla",
            "archetypes": ["matn", "cta"], "scenes": 2,
            "mood": "minimal", "backdrop": "hf_01.jpg"}


class TestThePlanOutlivesTheRequest:
    def test_a_saved_plan_comes_back_with_its_lines(self):
        bid = uuid.uuid4()
        clip_plans.save(bid, "SMM", a_job(), a_shape())
        plan = clip_plans.load(bid)
        assert plan is not None
        assert plan.says == ["Bir gap.", "Ikkinchi gap."]
        assert plan.topic == "SMM"

    def test_nothing_pending_reads_as_nothing_pending(self):
        assert clip_plans.load(uuid.uuid4()) is None

    def test_rendering_clears_it(self):
        bid = uuid.uuid4()
        clip_plans.save(bid, "SMM", a_job(), a_shape())
        clip_plans.clear(bid)
        assert clip_plans.load(bid) is None

    def test_clearing_twice_is_not_an_error(self):
        clip_plans.clear(uuid.uuid4())

    def test_a_newer_ask_replaces_the_older_one(self):
        """One clip at a time. A queue of half-finished scripts waiting on
        voice messages is a worse problem than losing the older of two."""
        bid = uuid.uuid4()
        clip_plans.save(bid, "birinchi", a_job(["Bir."]), a_shape())
        clip_plans.save(bid, "ikkinchi", a_job(["Ikki.", "Uch."]), a_shape())
        plan = clip_plans.load(bid)
        assert plan.topic == "ikkinchi" and len(plan.says) == 2

    def test_a_script_nobody_recorded_expires(self):
        """The topic has moved on; rendering it days later helps nobody."""
        bid = uuid.uuid4()
        path = clip_plans.save(bid, "SMM", a_job(), a_shape())
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["created"] = time.time() - clip_plans.MAX_AGE_SECONDS - 60
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert clip_plans.load(bid) is None

    def test_a_corrupt_file_reads_as_absent_rather_than_raising(self):
        """A bad file must not take a bot handler down with it."""
        bid = uuid.uuid4()
        path = clip_plans.save(bid, "SMM", a_job(), a_shape())
        path.write_text("{ this is not json", encoding="utf-8")
        assert clip_plans.load(bid) is None

    def test_a_plan_with_no_lines_is_not_worth_waiting_on(self):
        bid = uuid.uuid4()
        clip_plans.save(bid, "SMM", a_job([]), a_shape())
        assert clip_plans.load(bid) is None


class TestTheAgentSeparatesDecidingFromSpeaking:
    async def test_plan_returns_the_lines_without_voicing_them(self, monkeypatch):
        from app.agents.promo_brief import BriefPlan, BriefScene, PromoBriefAgent, SceneCopy
        from app.services import tts
        from tests.test_agents import make_business, make_knowledge

        async def never(*args, **kwargs):
            raise AssertionError("rejalashda ovoz sintez qilinmasligi kerak")

        monkeypatch.setattr(tts, "narrate", never)

        agent = PromoBriefAgent(session=None)

        async def fake_ask_json(prompt, schema, **kwargs):
            return BriefPlan.model_construct(mood="tezkor", scenes=[
                BriefScene(use="matn", say="Bir ikki uch to'rt.", text=SceneCopy()),
                BriefScene(use="cta", say="Bugun yozing.",
                           text=SceneCopy(title="Yozing")),
            ])

        monkeypatch.setattr(agent, "ask_json", fake_ask_json)
        monkeypatch.setattr(agent, "_recent", lambda business: _empty())
        monkeypatch.setattr(agent, "_library", lambda business, knowledge: [])

        planned = await agent.plan(make_business(), make_knowledge(), "SMM")
        assert planned.says == ["Bir ikki uch to'rt.", "Bugun yozing."]
        assert planned.shape.skeleton
        assert "scenes" in planned.job


async def _empty():
    return []


class TestItIsWiredToRun:
    def test_both_phases_are_registered(self):
        import app.tasks.generation  # noqa: F401
        from app.tasks.celery_app import celery_app

        for task in ("plan_brief_clip", "render_planned_clip"):
            assert f"app.tasks.generation.{task}" in celery_app.tasks

    def test_planning_and_rendering_do_not_share_a_time_limit(self):
        """One model call against minutes of browser is not one budget."""
        from app.tasks.celery_app import celery_app

        annotations = celery_app.conf.task_annotations
        plan = annotations["app.tasks.generation.plan_brief_clip"]["time_limit"]
        render = annotations["app.tasks.generation.render_planned_clip"]["time_limit"]
        assert plan < render

    def test_the_clip_command_now_plans_rather_than_renders(self):
        from pathlib import Path

        source = Path("app/bot/handlers/admin.py").read_text(encoding="utf-8")
        assert "app.tasks.generation.plan_brief_clip" in source
        assert "app.tasks.generation.render_planned_clip" in source

    def test_the_script_message_tells_the_reader_to_pause(self):
        """`tts.split` cuts on those pauses; without them there is no split."""
        from app.bot import texts

        assert "to'xtang" in texts.SCRIPT_READY
        assert "ovozli xabar" in texts.SCRIPT_READY
