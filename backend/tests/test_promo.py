"""The browser-rendered promo engine.

These cover the parts that are easy to get silently wrong: asset paths that
resolve to nothing, audio cues that drift away from the edit, and families that
let a model's copy overflow the layout it was authored for.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import promo
from app.services.promo_families import BPM, BUILDERS, FAMILIES, Brand
from app.services.music import snap_to_beat


def on_beat(value: float, bpm: int) -> bool:
    """snap_to_beat rounds to 3 decimals, so an exact modulo never lands."""
    beat = 60.0 / bpm
    offset = value % beat
    return min(offset, beat - offset) < 0.002


def script_with(**over):
    base = {
        "name": "t", "duration": 6.0, "fps": 30, "size": [1080, 1920],
        "palette": {"bg": "#000", "ink": "#fff", "accent": "#0f0"},
        "scenes": [
            {"at": [0.0, 3.0], "lines": [{"kind": "display", "text": "bir"}]},
            {"at": [3.0, 6.0], "lines": [{"kind": "display", "text": "ikki"}]},
        ],
    }
    base.update(over)
    return base


class TestAssetPaths:
    """A prop whose src does not resolve renders nothing, silently."""

    def test_a_relative_path_becomes_a_file_url(self):
        script = script_with()
        script["scenes"][0]["prop"] = {"src": "fonts/anton.ttf"}
        out = promo._localise(script)
        assert out["scenes"][0]["prop"]["src"].startswith("file://")

    def test_a_missing_prop_is_dropped_rather_than_left_broken(self):
        script = script_with()
        script["scenes"][0]["prop"] = {"src": "yoq/bunday/fayl.png"}
        out = promo._localise(script)
        assert "prop" not in out["scenes"][0]

    def test_an_http_source_is_left_alone(self):
        script = script_with()
        script["scenes"][0]["prop"] = {"src": "https://example.com/a.png"}
        assert promo._localise(script)["scenes"][0]["prop"]["src"].startswith("https://")

    def test_the_callers_script_is_never_mutated(self):
        script = script_with()
        script["scenes"][0]["prop"] = {"src": "yoq.png"}
        promo._localise(script)
        assert script["scenes"][0]["prop"]["src"] == "yoq.png"

    def test_an_absolute_path_that_exists_survives(self, tmp_path):
        real = tmp_path / "p.png"
        real.write_bytes(b"x")
        script = script_with()
        script["scenes"][0]["prop"] = {"src": str(real)}
        assert promo._localise(script)["scenes"][0]["prop"]["src"] == real.as_uri()


class TestCuesFollowTheEdit:
    """The script owns timing, so audio cannot drift out of sync with the cut."""

    def test_every_cut_gets_a_whoosh(self):
        cues = promo._cues(script_with())
        whooshes = sorted(at for name, at, _ in cues if name == "whoosh")
        assert whooshes == [0.0, pytest.approx(2.88)]

    def test_the_opening_has_no_impact_hit(self):
        impacts = [at for name, at, _ in promo._cues(script_with()) if name == "impact"]
        assert all(at > 0.5 for at in impacts)
        assert len(impacts) == 1

    def test_the_last_scene_gets_a_riser_into_it(self):
        cues = promo._cues(script_with())
        assert any(name == "riser" for name, _, _ in cues)


class TestFamilies:
    """Layout and timing are authored; a model only fills in copy."""

    @staticmethod
    def brand():
        return Brand.from_colors({"bg": "#141414", "accent": "#C9A227", "text": "#F5F2EA"},
                                 mark="Shanghai School", cta="Bepul dars")

    def sample(self, family: str) -> dict:
        b = self.brand()
        if family == "statement":
            return BUILDERS[family](b, kicker="K", hook=["A", "b", "C?"],
                                    problem=["M —", "X", "emas."], diagnosis=["S", "Y", "yo'q."],
                                    formula_title="F", formula=[("A", "AN", "d"), ("R", "RE", "d"), ("E", "EX", "d")],
                                    summary=["3 ta.", "Bitta."], headline="SHANGHAI")
        if family == "sanoq":
            return BUILDERS[family](b, title="5 ta xato", subtitle="s",
                                    items=[(f"H{i}", "w", "r") for i in range(5)], headline="SHANGHAI")
        if family == "taqqoslash":
            return BUILDERS[family](b, title=["Bitta.", "Ikki."],
                                    pairs=[{"wrong_label": "X", "wrong": "w",
                                            "right_label": "Y", "right": ["a", "b"]}] * 3,
                                    headline="SHANGHAI")
        if family == "savol":
            return BUILDERS[family](b, question=["q1", "q2"], options=["a", "b", "c"], correct=2,
                                    reasons=[("W", "d")] * 3, headline="SHANGHAI")
        if family == "raqam":
            return BUILDERS[family](b, title="Raqamlarda",
                                    stats=[{"value": 10, "suffix": "+", "label": "l"},
                                           {"value": 800, "label": "l"}], headline="SHANGHAI")
        if family == "ustoz":
            return BUILDERS[family](b, title="T", subtitle="s", caption="c",
                                    footage="/tmp/yoq.mp4", headline="SHANGHAI")
        if family == "uzluksiz":
            return BUILDERS[family](b, opening="A", middle="m", build="b", punch="p",
                                    tagline="t", headline="SHANGHAI")
        if family == "dastur":
            return BUILDERS[family](b, title="Sentabr", subtitle="jadval",
                                    groups=[{"title": "G", "rows": [{"left": "a", "right": "1"},
                                                                    {"left": "b", "right": "2"}]}],
                                    headline="SHANGHAI")
        if family == "muddat":
            return BUILDERS[family](b, kicker="K", pressure="P", count_from=12, count_to=3,
                                    count_label="joy", date_lead="D", date="2-SENTABR",
                                    date_tail="dan", headline="SHANGHAI")
        return BUILDERS[family](b, photo=None, badge="6.5 → 7.5", quote=["a", "b"],
                                attribution="N", changed_title="C",
                                changed=[("A", "AN", "d")] * 3, headline="SHANGHAI")

    @pytest.mark.parametrize("family", FAMILIES)
    def test_every_family_builds_a_renderable_script(self, family):
        script = self.sample(family)
        assert script["scenes"] and script["duration"] > 0
        assert script["family"] == family
        for scene in script["scenes"]:
            assert scene["at"][1] > scene["at"][0]

    @pytest.mark.parametrize("family", FAMILIES)
    def test_scenes_run_back_to_back_with_no_gap(self, family):
        scenes = self.sample(family)["scenes"]
        for before, after in zip(scenes, scenes[1:]):
            assert before["at"][1] == pytest.approx(after["at"][0])

    @pytest.mark.parametrize("family", FAMILIES)
    def test_every_cut_lands_on_the_beat(self, family):
        """The bed is tempo-locked; a cut off the pulse reads as a mistake.

        Each family runs at its own tempo, so this checks against that tempo —
        not a global one the family may not be playing.
        """
        from app.services.promo_families import profile

        bpm = profile(family)["bpm"]
        for scene in self.sample(family)["scenes"]:
            assert on_beat(scene["at"][0], bpm), (family, scene["at"][0], bpm)

    @pytest.mark.parametrize("family", FAMILIES)
    def test_the_last_scene_ends_at_the_declared_duration(self, family):
        script = self.sample(family)
        assert script["scenes"][-1]["at"][1] == pytest.approx(script["duration"])

    def test_a_long_list_is_capped_rather_than_overflowing_the_clip(self):
        script = BUILDERS["sanoq"](self.brand(), title="t", subtitle="s",
                                   items=[(f"H{i}", "w", "r") for i in range(20)],
                                   headline="H")
        assert len(script["scenes"]) == 6 + 2          # cap of 6, plus hook and CTA

    def test_brand_colours_map_the_stored_key_names(self):
        """The knowledge base stores `text`; the template wants `ink`."""
        b = Brand.from_colors({"text": "#ABCDEF", "accent": "#123456"})
        assert b.palette["ink"] == "#ABCDEF"
        assert b.palette["accent"] == "#123456"

    def test_a_business_with_no_colours_still_renders(self):
        b = Brand.from_colors(None)
        assert b.palette["accent"].startswith("#")
        assert b.glow().startswith("rgba(")

    def test_props_cycle_so_a_clip_never_repeats_one_back_to_back(self):
        b = Brand(props=["a.png", "b.png"])
        assert b.prop(0) != b.prop(1)
        assert b.prop(2) == b.prop(0)

    def test_no_props_is_not_an_error(self):
        assert Brand(props=[]).prop(0) is None


class TestNewFamiliesCarryTheirOwnShape:
    """The four newest families exist because each has a form the others lack."""

    @staticmethod
    def brand():
        return Brand.from_colors({"accent": "#C9A227"}, mark="Shanghai School", cta="Bepul")

    def test_the_continuous_family_never_cuts(self):
        """Its whole point: one frame held, copy accumulating, no edit at all."""
        script = BUILDERS["uzluksiz"](self.brand(), opening="A", middle="m", build="b",
                                      punch="p", tagline="t", headline="H")
        assert len(script["scenes"]) == 1
        assert script["scenes"][0]["at"] == [0.0, script["duration"]]
        assert script["flash"] == 0

    def test_nothing_leaves_the_continuous_scene(self):
        script = BUILDERS["uzluksiz"](self.brand(), opening="A", middle="m", build="b",
                                      punch="p", tagline="t", headline="H")
        for line in script["scenes"][0]["lines"]:
            assert line.get("out") == 99

    def test_the_countdown_counts_down_where_the_stat_counts_up(self):
        down = BUILDERS["muddat"](self.brand(), kicker="K", pressure="P", count_from=12,
                                  count_to=3, count_label="joy", date_lead="D",
                                  date="2-SENTABR", date_tail="dan", headline="H")
        number = next(ln for sc in down["scenes"] for ln in sc.get("lines", [])
                      if ln.get("kind") == "number")
        assert number["from"] > number["to"]

        up = BUILDERS["raqam"](self.brand(), title="t",
                               stats=[{"value": 800, "label": "l"}, {"value": 10, "label": "l"}],
                               headline="H")
        first = next(ln for sc in up["scenes"] for ln in sc.get("lines", [])
                     if ln.get("kind") == "number")
        assert first["from"] < first["to"]

    def test_the_schedule_renders_a_table_no_other_family_has(self):
        script = BUILDERS["dastur"](self.brand(), title="Sentabr", subtitle="jadval",
                                    groups=[{"title": "G", "rows": [{"left": "a", "right": "1"},
                                                                    {"left": "b", "right": "2"}]}],
                                    headline="H")
        tables = [ln for sc in script["scenes"] for ln in sc.get("lines", [])
                  if ln.get("kind") == "table"]
        assert tables and tables[0]["rows"][0] == {"left": "a", "right": "1"}

    def test_a_table_is_capped_at_four_rows(self):
        script = BUILDERS["dastur"](self.brand(), title="t", subtitle="s",
                                    groups=[{"title": "G",
                                             "rows": [{"left": str(i), "right": "x"} for i in range(9)]}],
                                    headline="H")
        table = next(ln for sc in script["scenes"] for ln in sc.get("lines", [])
                     if ln.get("kind") == "table")
        assert len(table["rows"]) == 4

    def test_the_footage_family_is_the_only_one_with_a_video(self):
        script = BUILDERS["ustoz"](self.brand(), title="T", subtitle="s", caption="c",
                                   footage="/tmp/x.mp4", headline="H")
        videos = [ln for sc in script["scenes"] for ln in sc.get("lines", [])
                  if ln.get("kind") == "video"]
        assert len(videos) == 1 and videos[0]["src"] == "/tmp/x.mp4"


class TestFamilySelection:
    """Which family a pillar gets, and what happens when an asset is missing."""

    def test_every_pillar_has_at_least_one_family(self):
        from app.agents.promo import PILLAR_FAMILIES
        from app.models.enums import ContentPillar

        for pillar in ContentPillar:
            assert PILLAR_FAMILIES.get(pillar), pillar

    def test_every_family_has_a_copy_schema(self):
        from app.agents.promo import SCHEMAS
        from app.services.promo_families import FAMILIES

        assert set(SCHEMAS) == set(FAMILIES)

    def test_every_mapped_family_can_actually_be_built(self):
        from app.agents.promo import PILLAR_FAMILIES

        mapped = {f for names in PILLAR_FAMILIES.values() for f in names}
        assert mapped <= set(BUILDERS)

    def test_a_family_needing_footage_is_not_chosen_without_it(self):
        """Otherwise the clip renders with a hole where the video should be."""
        from app.agents.promo import NEEDS_FOOTAGE, PILLAR_FAMILIES
        from app.models.enums import ContentPillar

        for pillar, names in PILLAR_FAMILIES.items():
            if any(n in NEEDS_FOOTAGE for n in names):
                assert [n for n in names if n not in NEEDS_FOOTAGE], pillar


class TestMusicVariety:
    """Ten distinct-looking families that all sound the same is nine wasted."""

    def test_there_is_more_than_one_progression(self):
        """There used to be exactly one, module-level, for every clip ever made."""
        from app.services.music import MOODS

        assert len(MOODS) >= 4
        voicings = {tuple(bars) for bars in MOODS.values()}
        assert len(voicings) == len(MOODS)          # no mood is a copy

    def test_every_family_declares_a_sound(self):
        from app.services.promo_families import FAMILIES, PROFILES

        assert set(PROFILES) == set(FAMILIES)
        for name, spec in PROFILES.items():
            assert spec["mood"] and spec["bpm"] > 0 and spec["energy"], name

    def test_no_two_families_share_the_same_signature(self):
        from app.services.promo_families import PROFILES

        signatures = [(s["mood"], s["bpm"], s["energy"]) for s in PROFILES.values()]
        assert len(set(signatures)) == len(signatures)

    def test_the_countdown_and_the_brand_piece_are_opposites(self):
        """A deadline and a brand film should not share a pulse."""
        from app.services.promo_families import PROFILES

        assert PROFILES["muddat"]["bpm"] > PROFILES["uzluksiz"]["bpm"] + 20
        assert PROFILES["muddat"]["mood"] != PROFILES["uzluksiz"]["mood"]

    def test_cuts_snap_to_the_family_tempo_not_a_global_one(self):
        """A cut on 120 while the bed plays 128 is worse than no alignment."""
        from app.services.promo_families import BUILDERS, Brand, PROFILES

        b = Brand.from_colors({"accent": "#C9A227"}, mark="M", cta="c")
        script = BUILDERS["muddat"](b, kicker="K", pressure="P", count_from=12, count_to=3,
                                    count_label="j", date_lead="D", date="D",
                                    date_tail="d", headline="H")
        bpm = PROFILES["muddat"]["bpm"]
        assert script["music"]["bpm"] == bpm
        assert bpm != BPM                          # not the global default
        for scene in script["scenes"]:
            assert on_beat(scene["at"][0], bpm)

    def test_a_brand_gets_its_own_key(self):
        from app.services.promo_families import Brand

        one = Brand.from_colors({}, mark="Shanghai School")
        two = Brand.from_colors({}, mark="Boshqa Markaz")
        assert -3 <= one.key_shift <= 3
        assert one.key_shift != two.key_shift

    def test_the_same_brand_always_gets_the_same_key(self):
        """A signature you hear only works if it does not move between clips."""
        from app.services.promo_families import Brand

        assert (Brand.from_colors({}, mark="Shanghai School").key_shift
                == Brand.from_colors({}, mark="Shanghai School").key_shift)

    def test_transposing_actually_changes_the_bed(self):
        from app.services.music import MusicSpec, render_bed

        plain = render_bed(MusicSpec(seconds=2.0, bpm=120))
        moved = render_bed(MusicSpec(seconds=2.0, bpm=120, key_shift=3))
        assert list(plain) != list(moved)

    def test_each_mood_produces_a_different_bed(self):
        from app.services.music import MOODS, MusicSpec, render_bed

        # Long enough for all four bars: `calm` and `tense` share an opening
        # chord, so a two-second sample cannot tell them apart.
        beds = {
            m: bytes(bed.left) + bytes(bed.right)
            for m in MOODS
            if (bed := render_bed(MusicSpec(seconds=9.0, bpm=120, mood=m)))
        }
        assert len(set(beds.values())) == len(MOODS)

    def test_rotation_moves_the_opening_chord(self):
        from app.services.music import MusicSpec, render_bed

        first = render_bed(MusicSpec(seconds=2.0, bpm=120, rotation=0))
        second = render_bed(MusicSpec(seconds=2.0, bpm=120, rotation=2))
        assert list(first) != list(second)

    def test_copy_drives_rotation_so_two_clips_differ(self):
        from app.services.promo_families import BUILDERS, Brand

        b = Brand.from_colors({}, mark="M", cta="c")
        one = BUILDERS["raqam"](b, title="Raqamlarda",
                                stats=[{"value": 10, "label": "yillik tajriba"},
                                       {"value": 800, "label": "o'quvchi"}], headline="H")
        two = BUILDERS["raqam"](b, title="Natijalar",
                                stats=[{"value": 7, "label": "kun"},
                                       {"value": 42, "label": "guruh soni bor"}], headline="H")
        assert one["music"]["rotation"] != two["music"]["rotation"]

    def test_the_old_progression_name_still_resolves(self):
        """Older callers import PROGRESSION directly."""
        from app.services.music import MOODS, PROGRESSION

        assert PROGRESSION == MOODS["calm"]


class TestCopyGate:
    """Copy is checked before rendering, not after — a clip costs minutes."""

    @staticmethod
    def scene(*lines):
        return {"scenes": [{"at": [0, 3], "lines": list(lines)}]}

    def test_a_blank_line_blocks(self):
        from app.services.promo_qc import blocking, inspect

        assert blocking(inspect(self.scene({"kind": "display", "text": "   "})))

    def test_scaffolding_the_model_forgot_to_fill_blocks(self):
        from app.services.promo_qc import blocking, inspect

        for junk in ("{{title}}", "TODO", "Lorem ipsum dolor", "<headline>"):
            assert blocking(inspect(self.scene({"kind": "serif", "text": junk}))), junk

    def test_a_one_character_headline_blocks(self):
        from app.services.promo_qc import blocking, inspect

        assert blocking(inspect(self.scene({"kind": "display", "text": "x"})))

    def test_a_repeated_sentence_warns_but_does_not_block(self):
        """Worth flagging, not worth failing a clip over."""
        from app.services.promo_qc import blocking, inspect

        script = self.scene({"kind": "body", "text": "Bu qator ikki marta keladi."},
                            {"kind": "body", "text": "Bu qator ikki marta keladi."})
        issues = inspect(script)
        assert not blocking(issues)
        assert any("takrorlangan" in i.detail for i in issues)

    def test_a_missing_call_to_action_warns(self):
        from app.services.promo_qc import inspect

        issues = inspect(self.scene({"kind": "display", "text": "Salom dunyo"}))
        assert any("pill" in i.detail for i in issues)

    def test_rows_and_tables_are_read_too(self):
        """Nested copy is still copy; a blank table cell ships a blank cell."""
        from app.services.promo_qc import blocking, inspect

        assert blocking(inspect(self.scene(
            {"kind": "row", "letter": "A", "word": "", "desc": "izoh"})))
        assert blocking(inspect(self.scene(
            {"kind": "table", "rows": [{"left": "Ingliz", "right": ""}]})))

    def test_a_real_family_script_passes_clean(self):
        from app.services.promo_qc import blocking, inspect
        from app.services.promo_families import BUILDERS, Brand

        b = Brand.from_colors({"accent": "#C9A227"}, mark="Shanghai School", cta="Bepul dars")
        script = BUILDERS["raqam"](b, title="Raqamlarda",
                                   stats=[{"value": 10, "suffix": "+", "label": "yillik tajriba"},
                                          {"value": 800, "label": "o'quvchi"}],
                                   headline="SHANGHAI")
        assert blocking(inspect(script)) == []

    def test_blocking_issues_sort_ahead_of_warnings(self):
        from app.services.promo_qc import inspect

        issues = inspect(self.scene({"kind": "display", "text": ""},
                                    {"kind": "body", "text": "Takror qator bu yerda."},
                                    {"kind": "body", "text": "Takror qator bu yerda."}))
        assert issues[0].blocking

    def test_the_agent_retries_once_before_giving_up(self):
        """One retry covers a bad turn; a second mostly buys latency."""
        from app.agents.promo import ATTEMPTS

        assert ATTEMPTS == 2


class TestReadingTime:
    """Family durations are fixed in code; the copy that fills them is not."""

    @staticmethod
    def brand():
        from app.services.promo_families import Brand
        return Brand.from_colors({"accent": "#C9A227"}, mark="Shanghai School", cta="Bepul")

    def test_reading_runs_alongside_the_reveal_not_after_it(self):
        """Lines land one by one and are read as they land."""
        from app.services.promo_qc import reading_time

        scene = {"at": [0, 5], "lines": [
            {"kind": "display", "text": "bir ikki uch", "at": 0.1},
            {"kind": "body", "text": "tort besh olti yetti", "at": 2.0},
        ]}
        assert reading_time(scene) < 2.0 + 0.52 + 7 / 6.0

    def test_a_scene_must_at_least_finish_assembling(self):
        """Two words in a scene whose last line lands at 3s still needs 3s."""
        from app.services.promo_qc import SETTLE_MARGIN, reading_time

        scene = {"at": [0, 9], "lines": [{"kind": "display", "text": "ha", "at": 3.0}]}
        assert reading_time(scene) == pytest.approx(3.0 + 0.52 + SETTLE_MARGIN)

    def test_copy_far_longer_than_the_slot_is_flagged(self):
        from app.services.promo_qc import inspect

        scene = {"scenes": [{"at": [0, 2], "lines": [
            {"kind": "body", "text": " ".join(["soz"] * 40), "at": 0.1},
            {"kind": "pill", "text": "Bepul"},
        ]}]}
        assert any("o'qish uchun" in i.detail for i in inspect(scene))

    def test_a_reading_problem_warns_rather_than_blocks(self):
        """Tight is a judgement call; blank is not. Only blank stops a render."""
        from app.services.promo_qc import blocking, inspect

        scene = {"scenes": [{"at": [0, 2], "lines": [
            {"kind": "body", "text": " ".join(["soz"] * 40), "at": 0.1},
        ]}]}
        assert not blocking(inspect(scene))

    @pytest.mark.parametrize("family", FAMILIES)
    def test_every_shipped_family_reads_comfortably(self, family):
        """The threshold is calibrated against these; a failure means the
        family's own timing is wrong, not that the check is noisy."""
        from app.services.promo_qc import inspect

        script = TestFamilies().sample(family)
        slow = [i.detail for i in inspect(script) if "o'qish uchun" in i.detail]
        assert slow == []


class TestMediaReadiness:
    """Both of these degrade silently, which is the worst way to degrade."""

    def test_an_unconfigured_image_provider_is_reported(self, monkeypatch):
        from app.core.config import settings
        from app.services import brand_assets

        monkeypatch.setattr(settings, "image_provider", "none")
        state = brand_assets.media_readiness("biz")
        assert state["image_provider_ready"] is False

    def test_a_configured_provider_needs_its_key(self, monkeypatch):
        from app.core.config import settings
        from app.services import brand_assets

        monkeypatch.setattr(settings, "image_provider", "fal")
        monkeypatch.setattr(settings, "fal_api_key", "")
        assert brand_assets.media_readiness("biz")["image_provider_ready"] is False

        monkeypatch.setattr(settings, "fal_api_key", "k-123")
        assert brand_assets.media_readiness("biz")["image_provider_ready"] is True

    def test_the_owner_is_told_props_will_be_missing(self, monkeypatch):
        from app.bot.handlers.admin import _media_summary
        from app.core.config import settings

        monkeypatch.setattr(settings, "image_provider", "none")
        assert "IMAGE_PROVIDER" in _media_summary("biz")

    def test_the_owner_is_told_footage_changes_the_family(self, monkeypatch):
        from app.bot.handlers.admin import _media_summary
        from app.services import brand_assets

        monkeypatch.setattr(brand_assets, "footage_library", lambda _: [])
        assert "matnli shablon" in _media_summary("biz")
