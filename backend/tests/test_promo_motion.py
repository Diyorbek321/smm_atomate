"""Cuts on the pulse, and lines that settle instead of stopping dead.

Two things separate a motion-designed frame from an animated one, and the
engine was missing both.

`music.py` has had `snap_to_beat` since the families engine, whose own
docstring says *"Cuts land on the beat because the bed is tempo-locked"*. The
archetype engine replaced that engine and never called it, so scene length came
from the narration alone and the edit floated free of its own music. An
off-beat cut is the fastest thing to read as amateur, and the ear notices it
before the eye does.

The entries had one overshoot between them — `scale` — and everything else
decelerated to a dead stop.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.music import snap_to_beat
from app.services.promo_families import Brand
from app.services.promo_scenes import DEFAULT_BPM, TAIL, build_script

BRAND = Brand.from_colors({}, mark="Sinov", cta="Yozing")
TEMPLATE = Path("app/assets/promo/template.html").read_text(encoding="utf-8")


def script_for(durations: list[float], *, bpm: int = 126, **job_extra):
    job = {
        "name": "beat", "mood": "tezkor", "bpm": bpm,
        "scenes": [{"use": "matn", "slot": f"s{i}", "say": i}
                   for i in range(len(durations))],
        "say": ["Bir ikki uch to'rt." for _ in durations],
        "text": {f"s{i}": {} for i in range(len(durations))},
        **job_extra,
    }
    timing = [{"src": f"/v{i}.wav", "dur": d, "words": []}
              for i, d in enumerate(durations)]
    return build_script(job, BRAND, timing=timing)


#: `snap_to_beat` rounds its answer to milliseconds, so a "whole" beat is only
#: whole to within half a millisecond, and that error accumulates across scenes.
#: Tolerating it in seconds rather than in beats keeps the assertion about what
#: a listener could hear: 5ms of drift across a clip is inaudible, and anything
#: that fails this is a real off-beat cut rather than a rounding artefact.
DRIFT = 0.005


def off_beat(seconds: float, bpm: int) -> float:
    """How far this moment sits from the nearest beat, in seconds."""
    beat = 60.0 / bpm
    return abs(seconds - round(seconds / beat) * beat)


class TestEveryCutLandsOnTheBeat:
    @pytest.mark.parametrize("bpm", [100, 112, 118, 126])
    def test_at_any_tempo_the_skeletons_use(self, bpm):
        script = script_for([2.4, 1.8, 3.3, 0.9], bpm=bpm)
        for scene in script["scenes"]:
            for edge in scene["at"]:
                assert off_beat(edge, bpm) < DRIFT, f"{edge}s @ {bpm}bpm"

    def test_each_scene_is_a_whole_number_of_beats(self):
        """The invariant the composer actually enforces, scene by scene."""
        bpm = 126
        script = script_for([2.4, 1.83, 3.31, 0.55], bpm=bpm)
        for scene in script["scenes"]:
            length = scene["at"][1] - scene["at"][0]
            assert off_beat(length, bpm) < DRIFT, length

    def test_the_whole_clip_ends_on_the_beat_too(self):
        assert off_beat(script_for([2.4, 1.83, 3.31])["duration"], 126) < DRIFT

    def test_a_scene_is_never_shortened_below_its_narration(self):
        """Rounding down would cut somebody off mid-word."""
        durations = [2.4, 1.83, 3.31, 0.55]
        script = script_for(durations)
        for spoken, scene in zip(durations, script["scenes"], strict=True):
            length = scene["at"][1] - scene["at"][0]
            assert length >= spoken + TAIL - 1e-6

    def test_it_adds_air_rather_than_a_whole_bar(self):
        """The rounding is to the beat, not to the bar.

        Snapping to a bar would pad a two-second line out to four and turn a
        tight edit into a slideshow.
        """
        script = script_for([2.4])
        assert script["duration"] - (2.4 + TAIL) < 60.0 / 126

    def test_an_authored_length_is_left_alone(self):
        """Someone typed that number; the bed does not overrule it."""
        job = {
            "name": "b", "mood": "tezkor", "bpm": 126,
            "scenes": [{"use": "matn", "slot": "s0", "dur": 3.7, "say": 0}],
            "say": ["Bir ikki."], "text": {"s0": {}},
        }
        script = build_script(job, BRAND)
        assert script["scenes"][0]["at"] == [0.0, 3.7]

    def test_a_silent_estimate_is_snapped_as_well(self):
        """A mute draft is still an edit, and still gets cut to the pulse."""
        job = {
            "name": "b", "mood": "tezkor", "bpm": 126,
            "scenes": [{"use": "matn", "slot": "s0", "say": 0}],
            "say": ["bir ikki uch to'rt besh"], "text": {"s0": {}},
        }
        end = build_script(job, BRAND)["scenes"][0]["at"][1]
        assert off_beat(end, 126) < DRIFT

    def test_the_tempo_that_snaps_is_the_one_that_plays(self):
        script = script_for([2.4], bpm=104)
        assert script["music"]["bpm"] == 104
        assert script["duration"] == snap_to_beat(2.4 + TAIL, 104)

    def test_without_a_tempo_it_falls_back_to_the_default(self):
        job = {
            "name": "b", "mood": "tezkor",
            "scenes": [{"use": "matn", "slot": "s0", "say": 0}],
            "say": ["Bir ikki."], "text": {"s0": {}},
        }
        script = build_script(job, BRAND, timing=[{"src": "/a.wav", "dur": 2.4, "words": []}])
        assert script["duration"] == snap_to_beat(2.4 + TAIL, DEFAULT_BPM)


class TestLinesSettleRatherThanStop:
    @staticmethod
    def _ease(c1: float, t: float) -> float:
        c3 = c1 + 1
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

    def test_a_settle_easing_ships(self):
        assert "const eOutSettle=" in TEMPLATE

    def test_it_overshoots_but_less_than_a_prop_does(self):
        """Type that springs as hard as a bouncing object reads as a toy."""
        settle = max(self._ease(0.85, i / 1000) for i in range(1001))
        prop = max(self._ease(1.34, i / 1000) for i in range(1001))
        assert 1.0 < settle < prop

    def test_it_lands_exactly_on_target(self):
        assert self._ease(0.85, 1.0) == pytest.approx(1.0)

    def test_moving_entries_settle_and_mask_does_not(self):
        """A clip-path past 100% is not an overshoot, it is an invalid rect."""
        chosen = re.search(r"const ease = ([\s\S]{0,220}?);", TEMPLATE).group(1)
        assert "'mask'" in chosen and "eOutExpo" in chosen
        assert "eOutSettle" in chosen

    def test_the_strong_overshoot_is_still_used_where_it_belongs(self):
        assert "eOutBack" in TEMPLATE
