"""Composing a promo script out of scene archetypes.

The composer is where an authored layout and model-written copy meet, so the
failures worth testing are the quiet ones: a placeholder that resolves to
nothing and renders an empty line, a repeated row that loses its index, a
counter that arrives as a string and never counts.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ConfigurationError
from app.services import promo_scenes
from app.services.promo_families import Brand
from app.services.promo_scenes import archetype_names, build_script, catalogue, spread_words

BRAND = Brand.from_colors(
    {"bg": "#0F2B63", "ink": "#FFFFFF", "accent": "#FFCE1B", "muted": "#8CA3C7"},
    mark="Postchi", cta="@inovatex",
)


def job_with(scenes, **over):
    base = {"name": "sinov", "scenes": scenes, "say": [], "text": {}}
    base.update(over)
    return base


def only(lines, kind):
    """The one line of this kind in a scene."""
    return next(line for line in lines if line["kind"] == kind)


def every(lines, kind):
    return [line for line in lines if line["kind"] == kind]


def timing_for(*durations):
    return [{"src": f"vo/{i}.wav", "dur": d, "words": [{"w": "bir", "at": 0.0, "b": False}]}
            for i, d in enumerate(durations)]


class TestArchetypes:
    """The shipped catalogue has to stay renderable on its own."""

    def test_every_shipped_archetype_composes(self):
        # A malformed archetype file would otherwise only surface when a model
        # happened to pick that one, days later, in a real clip.
        for name in archetype_names():
            script = build_script(_job_for(name), BRAND)
            assert script["scenes"], name

    def test_the_catalogue_describes_every_file(self):
        described = {entry["name"] for entry in catalogue()}
        assert described == set(archetype_names())
        assert all(entry["desc"] for entry in catalogue())

    def test_an_unknown_archetype_names_the_alternatives(self):
        with pytest.raises(ConfigurationError, match="yoq.*Mavjudlari|Mavjudlari"):
            build_script(job_with([{"use": "bunday-arxetip-yoq", "dur": 2}]), BRAND)

    def test_a_reference_overrides_the_archetype_it_names(self):
        script = build_script(
            job_with([{"use": "matn", "dur": 3.0, "align": "left"}]), BRAND
        )
        assert script["scenes"][0]["align"] == "left"      # archetype says center


class TestPlaceholders:
    def test_a_slot_reaches_this_scenes_own_copy(self):
        script = build_script(
            job_with([{"use": "cta", "slot": "a", "dur": 2}], text={"a": {"headline": "Salom"}}),
            BRAND,
        )
        assert script["scenes"][0]["lines"][0]["text"] == "Salom"

    def test_one_archetype_used_twice_keeps_its_two_texts_apart(self):
        script = build_script(
            job_with(
                [{"use": "cta", "slot": "a", "dur": 2}, {"use": "cta", "slot": "b", "dur": 2}],
                text={"a": {"headline": "Bir"}, "b": {"headline": "Ikki"}},
            ),
            BRAND,
        )
        assert [s["lines"][0]["text"] for s in script["scenes"]] == ["Bir", "Ikki"]

    def test_brand_fields_resolve(self):
        script = build_script(
            job_with([{"use": "cta", "slot": "a", "dur": 2}], text={"a": {"headline": "X"}}),
            BRAND,
        )
        pill = only(script["scenes"][0]["lines"], "pill")
        assert pill["text"] == "@inovatex"

    def test_an_optional_field_falls_back_rather_than_failing(self):
        # iqtibos's author is `author?`; a quote with no attribution is valid.
        script = build_script(
            job_with([{"use": "iqtibos", "slot": "a", "dur": 3}],
                     text={"a": {"quote": "Gap"}}),
            BRAND,
        )
        kicker = only(script["scenes"][0]["lines"], "kicker")
        assert kicker["text"] == ""

    def test_a_missing_required_field_names_itself(self):
        with pytest.raises(ConfigurationError, match="s.headline"):
            build_script(job_with([{"use": "cta", "slot": "s", "dur": 2}], text={"s": {}}), BRAND)

    def test_a_solo_placeholder_holding_a_number_stays_a_number(self):
        # `to` drives a counter. As the string "83" it renders once and the
        # count never animates.
        script = build_script(
            job_with([{"use": "stat", "slot": "a", "dur": 4}],
                     text={"a": {"label": "L", "to": "83", "suffix": "%"}}),
            BRAND,
        )
        assert script["scenes"][0]["lines"][0]["to"] == 83

    def test_a_placeholder_inside_a_sentence_is_substituted(self):
        script = build_script(
            job_with([{"use": "matn", "dur": 2,
                       "lines": [{"kind": "body", "text": "Salom, {{brand.mark}}!"}]}]),
            BRAND,
        )
        assert script["scenes"][0]["lines"][0]["text"] == "Salom, Postchi!"


class TestRepeatedRows:
    def test_a_list_becomes_one_row_per_entry(self):
        script = build_script(
            job_with([{"use": "royxat", "slot": "a", "dur": 5}],
                     text={"a": {"title": "T", "items": ["bir", "ikki", "uch"]}}),
            BRAND,
        )
        rows = every(script["scenes"][0]["lines"], "row")
        assert [r["word"] for r in rows] == ["bir", "ikki", "uch"]

    def test_rows_are_numbered_from_one(self):
        script = build_script(
            job_with([{"use": "royxat", "slot": "a", "dur": 5}],
                     text={"a": {"title": "T", "items": ["bir", "ikki"]}}),
            BRAND,
        )
        rows = every(script["scenes"][0]["lines"], "row")
        assert [r["letter"] for r in rows] == [1, 2]

    def test_each_row_lands_later_than_the_one_before(self):
        script = build_script(
            job_with([{"use": "royxat", "slot": "a", "dur": 5}],
                     text={"a": {"title": "T", "items": ["bir", "ikki", "uch"]}}),
            BRAND,
        )
        ats = [line["at"] for line in every(script["scenes"][0]["lines"], "row")]
        assert ats == sorted(ats) and len(set(ats)) == 3

    def test_a_list_of_objects_keeps_its_fields(self):
        script = build_script(
            job_with([{"use": "narx", "slot": "a", "dur": 4}],
                     text={"a": {"title": "T",
                                 "rows": [{"left": "Boshlang'ich", "right": "490"}]}}),
            BRAND,
        )
        table = only(script["scenes"][0]["lines"], "table")
        assert table["rows"] == [{"left": "Boshlang'ich", "right": "490"}]

    def test_a_repeat_over_something_that_is_not_a_list_is_reported(self):
        with pytest.raises(ConfigurationError, match="s.items"):
            build_script(
                job_with([{"use": "auditoriya", "slot": "s", "dur": 3}],
                         text={"s": {"items": "bitta satr"}}),
                BRAND,
            )


class TestTiming:
    def test_measured_speech_sets_the_scene_length(self):
        """Speech sets the floor; the pulse sets where the cut actually lands.

        4.0s of audio plus the tail is 4.22s, and the cut is rounded up from
        there to the next beat. Up, never down: a scene pulled back onto the
        previous beat would cut the narration off mid-word.
        """
        from app.services.music import snap_to_beat
        from app.services.promo_scenes import DEFAULT_BPM

        script = build_script(
            job_with([{"use": "matn", "say": 0}], say=["bir ikki"]),
            BRAND, timing=timing_for(4.0),
        )
        end = script["scenes"][0]["at"][1]
        assert end == snap_to_beat(4.22, DEFAULT_BPM)
        assert end >= 4.22

    def test_scenes_run_back_to_back(self):
        script = build_script(
            job_with([{"use": "matn", "say": 0}, {"use": "matn", "say": 1}],
                     say=["bir", "ikki"]),
            BRAND, timing=timing_for(3.0, 2.0),
        )
        first, second = script["scenes"]
        assert first["at"][1] == second["at"][0]
        assert script["duration"] == second["at"][1]

    def test_a_clip_with_no_speech_still_gets_a_length(self):
        # The synthesiser has a daily quota. A draft that renders mute beats a
        # render that never happened, so length is estimated from the words.
        script = build_script(
            job_with([{"use": "matn", "say": 0}], say=["bir ikki uch to'rt besh"]),
            BRAND,
        )
        from app.services.music import snap_to_beat
        from app.services.promo_scenes import DEFAULT_BPM

        assert script["scenes"][0]["at"][1] == snap_to_beat(
            5 / 150 * 60 + 0.6, DEFAULT_BPM
        )

    def test_a_scene_with_no_length_at_all_is_refused(self):
        with pytest.raises(ConfigurationError, match="na «clip», na «say», na «dur»"):
            build_script(job_with([{"use": "matn"}]), BRAND)

    def test_speech_lines_the_job_does_not_carry_are_refused(self):
        with pytest.raises(ConfigurationError, match="gapni so'rayapti"):
            build_script(job_with([{"use": "matn", "say": 3}], say=["bir"]), BRAND)


class TestKaraoke:
    def test_measured_words_win(self):
        script = build_script(
            job_with([{"use": "matn", "say": 0}], say=["yozilgan matn"]),
            BRAND, timing=timing_for(3.0),
        )
        line = script["scenes"][0]["lines"][0]
        assert [w["w"] for w in line["words"]] == ["bir"]      # from the timing

    def test_narration_is_spread_when_nothing_measured_it(self):
        script = build_script(
            job_with([{"use": "matn", "say": 0}], say=["bir ikki uch"]),
            BRAND,
        )
        assert [w["w"] for w in script["scenes"][0]["lines"][0]["words"]] == \
            ["bir", "ikki", "uch"]

    def test_spread_words_rise_and_stay_inside_the_scene(self):
        words = spread_words("bir ikki uch to'rt", 4.0)
        ats = [w["at"] for w in words]
        assert ats == sorted(ats) and ats[0] == 0.0 and ats[-1] < 4.0

    def test_an_asterisk_marks_emphasis_and_leaves_the_word_clean(self):
        words = spread_words("oddiy *muhim* oddiy", 3.0)
        assert [w["b"] for w in words] == [False, True, False]
        assert words[1]["w"] == "muhim"


class TestScript:
    def test_bookkeeping_never_reaches_the_renderer(self):
        script = build_script(
            job_with([{"use": "cta", "slot": "a", "say": 0, "dur": 2}],
                     say=["gap"], text={"a": {"headline": "X"}}),
            BRAND,
        )
        scene = script["scenes"][0]
        assert not {"use", "slot", "say", "needs", "desc", "tail"} & set(scene)

    def test_the_mark_clears_before_the_closing_scene(self):
        script = build_script(
            job_with([{"use": "matn", "dur": 3}, {"use": "cta", "slot": "a", "dur": 3}],
                     text={"a": {"headline": "X"}}),
            BRAND,
        )
        assert script["mark"]["until"] == pytest.approx(script["scenes"][-1]["at"][0] - 0.1)

    def test_an_uzbek_mood_becomes_one_the_bed_can_play(self):
        from app.services.music import MOODS
        for uzbek, mapped in promo_scenes.MOODS.items():
            script = build_script(job_with([{"use": "matn", "dur": 2}], mood=uzbek), BRAND)
            assert script["music"]["mood"] == mapped
            assert script["music"]["mood"] in MOODS

    def test_an_unknown_mood_falls_back_rather_than_failing(self):
        script = build_script(job_with([{"use": "matn", "dur": 2}], mood="yoq"), BRAND)
        assert script["music"]["mood"] == "calm"

    def test_the_brands_key_carries_into_the_bed(self):
        script = build_script(job_with([{"use": "matn", "dur": 2}]), BRAND)
        assert script["music"]["key_shift"] == BRAND.key_shift

    def test_two_names_do_not_open_on_the_same_chord(self):
        rotations = {
            build_script(job_with([{"use": "matn", "dur": 2}], name=n), BRAND)["music"]["rotation"]
            for n in ("bir", "ikki", "uch", "tort")
        }
        assert len(rotations) > 1

    def test_an_empty_job_is_refused(self):
        with pytest.raises(ConfigurationError, match="sahna yo'q"):
            build_script(job_with([]), BRAND)


#: Minimal valid copy for each shipped archetype, so the catalogue can be swept.
_COPY: dict[str, dict] = {
    "auditoriya": {"items": ["bir", "ikki"]},
    "belgilar": {"a_text": "Suv", "b_text": "Po'lat", "c_text": "Kafolat"},
    "cta": {"headline": "Salom"},
    "formula": {"title": "T", "items": [
        {"letter": "A", "word": "ANSWER", "desc": "javob"},
        {"letter": "R", "word": "REASON", "desc": "sabab"}]},
    "iqtibos": {"quote": "Gap", "author": "Kim"},
    "kartochka": {"leftTitle": "a", "leftBody": "b", "rightTitle": "c", "rightBody": "d"},
    # The photo scenes carry no copy of their own beyond the narration; the
    # picture is attached to the scene reference, not written by the model.
    "kadr": {},
    "kadrstat": {"label": "L", "to": 50},
    "matn": {},
    "narx": {"title": "T", "rows": [{"left": "a", "right": "b"}]},
    "qadamlar": {"title": "T", "items": ["bir", "ikki"]},
    "royxat": {"title": "T", "items": ["bir", "ikki"]},
    "sanoq": {"to": 10, "caption": "izoh"},
    "sarlavha": {"lines": [{"text": "BIR"}, {"text": "IKKI"}]},
    "stat": {"label": "L", "to": 50},
    "taqqoslash": {"leftTitle": "a", "leftBody": "b", "rightTitle": "c", "rightBody": "d"},
    "tuzatish": {"setup": "Muammo —", "wrong": "GRAMMATIKA"},
}


def _job_for(name: str) -> dict:
    assert name in _COPY, f"«{name}» arxetipi uchun sinov matni yozilmagan"
    return job_with([{"use": name, "slot": "s", "dur": 4.0}], text={"s": _COPY[name]})
