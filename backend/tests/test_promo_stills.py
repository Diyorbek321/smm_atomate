"""Photo scenes: the picture as the subject, not as texture behind it.

`S.background` runs one image under the whole clip at low contrast. That adds
texture and it is not what makes a good short-form clip good — those put the
photograph *on screen*, full frame, with one line over it. The template had
`kind: photo` lines and a full-bleed `footage` branch for video, and no
archetype used either, so every clip a business shipped was pure vector.

Two things need holding here. The picture must be attached by the agent, never
named by the model — a model asked for a filename invents one. And a clip must
not become all photographs: the rhythm that reads as edited is picture, card,
picture, and the authored graphic scenes are the card.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from app.agents.promo_brief import MAX_STILLS, STILL_TWIN, PromoBriefAgent
from app.services.promo_scenes import archetype_names, needs_still
from tests.test_agents import make_business
from tests.test_promo_brief import plan_with, scene

SHELF: list[str] = [f"/brand/x/photos/hf_{i:02d}.jpg" for i in range(1, 6)]


def build(scenes, stills=SHELF):
    from app.agents.promo_brief import BriefPlan

    plan = plan_with(*scenes) if not isinstance(scenes, BriefPlan) else scenes
    return PromoBriefAgent(session=None)._job(
        plan, make_business(id=uuid.uuid4()), "SMM", None, None, "", stills
    )


class TestTheArchetypesDeclareThemselves:
    def test_both_photo_scenes_ship(self):
        assert {"kadr", "kadrstat"} <= set(archetype_names())

    def test_only_the_photo_archetypes_ask_for_a_picture(self):
        asking = {n for n in archetype_names() if needs_still(n)}
        assert asking == {"kadr", "kadrstat", "belgilar"}

    def test_every_photo_archetype_can_degrade(self):
        """A picture-less shelf must not leave a scene with nothing to draw."""
        from app.agents.promo_brief import STILL_TWIN

        for name in archetype_names():
            if needs_still(name):
                assert name in STILL_TWIN, name

    def test_every_photo_scene_has_a_graphic_twin_that_exists(self):
        for photo, twin in STILL_TWIN.items():
            assert needs_still(photo), photo
            assert twin in archetype_names(), twin
            assert not needs_still(twin), twin


class TestThePictureIsAttachedNotChosen:
    def test_a_photo_scene_gets_a_source(self):
        job, _, _ = build([scene("kadr")])
        assert job["scenes"][0]["still"]["src"] in SHELF

    def test_a_graphic_scene_gets_none(self):
        job, _, _ = build([scene("matn")])
        assert "still" not in job["scenes"][0]

    def test_two_photo_scenes_do_not_share_one_picture(self):
        job, _, _ = build([scene("kadr"), scene("kadr")])
        srcs = [s["still"]["src"] for s in job["scenes"]]
        assert len(set(srcs)) == 2

    def test_the_copy_still_lands_under_the_archetypes_own_names(self):
        job, dropped, _ = build([scene("kadrstat", title="Xato", to=70)])
        assert not dropped
        assert job["text"]["s0"] == {"label": "Xato", "to": 70}


class TestTheRhythmIsProtected:
    def test_a_clip_of_nothing_but_photographs_is_not_allowed(self):
        job, dropped, _ = build([scene("kadr") for _ in range(6)])
        with_still = [s for s in job["scenes"] if "still" in s]
        assert len(with_still) == MAX_STILLS
        # And the excess is degraded, not dropped: the clip keeps its argument.
        assert not dropped
        assert len(job["scenes"]) == 6

    def test_the_excess_becomes_its_graphic_twin(self):
        job, _, _ = build([scene("kadr") for _ in range(MAX_STILLS + 2)])
        assert [s["use"] for s in job["scenes"]][-2:] == ["matn", "matn"]

    def test_a_stat_twin_keeps_the_numbers(self):
        scenes = [scene("kadrstat", title="X", to=1) for _ in range(MAX_STILLS + 1)]
        job, dropped, _ = build(scenes)
        assert not dropped
        assert job["scenes"][-1]["use"] == "stat"
        assert job["text"][job["scenes"][-1]["slot"]] == {"label": "X", "to": 1}


class TestAnEmptyShelfDegradesRatherThanBreaks:
    def test_a_business_with_no_pictures_still_gets_a_clip(self):
        job, dropped, _ = build([scene("kadr"), scene("matn")], stills=[])
        assert not dropped
        assert [s["use"] for s in job["scenes"]] == ["matn", "matn"]
        assert all("still" not in s for s in job["scenes"])

    def test_a_photo_stat_falls_back_with_its_copy_intact(self):
        job, dropped, _ = build([scene("kadrstat", title="X", to=9)], stills=[])
        assert not dropped
        assert job["scenes"][0]["use"] == "stat"
        assert job["text"]["s0"] == {"label": "X", "to": 9}


class TestTheScriptCarriesThePicture:
    LINE: ClassVar[dict] = {"src": "/brand/x/photos/hf_01.jpg"}

    def test_the_still_survives_into_the_rendered_script(self):
        from app.services.promo_families import Brand
        from app.services.promo_scenes import build_script

        job = {
            "name": "s", "mood": "tezkor",
            "scenes": [{"use": "kadr", "slot": "s0", "say": 0, "still": self.LINE}],
            "say": ["Bir ikki uch to'rt."], "text": {"s0": {}},
        }
        script = build_script(job, Brand.from_colors({}, mark="S", cta="Y"))
        assert script["scenes"][0]["still"]["src"] == self.LINE["src"]

    def test_a_missing_file_drops_the_picture_not_the_scene(self):
        from app.services.promo import _localise

        script = {"scenes": [{"still": {"src": "/yo-q/rasm.jpg"}, "lines": []}]}
        out = _localise(script)
        assert "still" not in out["scenes"][0]


class TestTheNumberDoesNotInventItsUnit:
    """`{{s.suffix|%}}` turned "14 customers" into "14%".

    The default was there so a percentage still rendered when a model forgot
    the suffix. The trade is the wrong way round: a missing % is a bare number
    the narration explains anyway, an invented % is a false claim in a client's
    advertising. Empty default, and the model is still told to supply one.
    """

    @staticmethod
    def _rendered(text: dict, use: str = "kadrstat") -> str:
        import json

        from app.services.promo_families import Brand
        from app.services.promo_scenes import build_script

        job = {
            "name": "s", "mood": "tezkor",
            "scenes": [{"use": use, "slot": "s0", "say": 0,
                        "still": {"src": "/brand/x/photos/hf_01.jpg"}}],
            "say": ["Bir ikki uch."], "text": {"s0": text},
        }
        return json.dumps(build_script(job, Brand.from_colors({}, mark="S", cta="Y")),
                          ensure_ascii=False)

    def test_a_count_renders_without_a_percent_sign(self):
        out = self._rendered({"label": "mijoz keldi", "to": 14})
        assert "14%" not in out

    def test_an_explicit_percent_survives(self):
        assert "70%" in self._rendered({"label": "xato", "to": 70, "suffix": "%"})

    def test_the_capsule_scene_is_held_to_the_same_rule(self):
        job_text = {"label": "mijoz keldi", "to": 14}
        import json

        from app.services.promo_families import Brand
        from app.services.promo_scenes import build_script

        script = build_script(
            {"name": "s", "mood": "tezkor",
             "scenes": [{"use": "stat", "slot": "s0", "say": 0}],
             "say": ["Bir ikki uch."], "text": {"s0": job_text}},
            Brand.from_colors({}, mark="S", cta="Y"))
        assert "14%" not in json.dumps(script, ensure_ascii=False)


class TestTelegramReachesTheEngineThisWorkIsIn:
    """`/klip` pointed at the families engine the whole time.

    Everything built here — skeleton rotation, motion, tempo, backdrops, photo
    scenes, narration — lives behind `render_brief_clip`. The bot enqueued
    `render_promo_clip`, so an owner asking for a clip in Telegram got one of
    ten authored layouts chosen by a hash of the topic, and none of it. The
    difference was not in the rendering; it was two different front doors.
    """

    def test_the_clip_command_queues_the_archetype_engine(self):
        from pathlib import Path

        source = Path("app/bot/handlers/admin.py").read_text(encoding="utf-8")
        # The entry point split in two when the owner started reading their own
        # script; what matters here is unchanged — neither half is the families
        # engine `/klip` used to reach.
        assert "app.tasks.generation.plan_brief_clip" in source
        assert "app.tasks.generation.render_planned_clip" in source
        assert "app.tasks.generation.render_promo_clip" not in source
