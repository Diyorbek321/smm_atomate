"""Why every clip came out the same shape, and what now stops it.

The engine could compose thousands of clips — eleven archetypes, a sequence a
model picks — and shipped one. The skeleton sat in the prompt as a constant, so
every clip opened on a number, ran eight scenes and signed off identically; the
archetypes moved underneath and no viewer could tell, because structure is what
gets remembered.

:mod:`app.utils.similarity` had guarded the *words* since the beginning. These
lock the other half: the shape rotates, it is chosen from what shipped rather
than fixed, and a draft that comes back looking like last week's is sent back.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.services.promo_variety import (
    GUARD_WINDOW,
    SKELETONS,
    TOO_CLOSE,
    Shape,
    avoid_note,
    choose,
    closeness,
    too_close,
)


def shape(skeleton: str, *archetypes: str) -> Shape:
    """A shipped clip, with its opening taken from the skeleton that made it."""
    opening = next((s.opening for s in SKELETONS if s.name == skeleton), "")
    return Shape(skeleton=skeleton, opening=opening,
                 archetypes=tuple(archetypes), scenes=len(archetypes))


class TestTheSkeletonIsNoLongerAConstant:
    """The bug: one skeleton in the prompt, so one shape in the output."""

    def test_the_pool_offers_genuinely_different_openings(self):
        # Rotation is worthless if two shapes start the same way — the opening
        # is the part a viewer clocks first.
        openings = [s.opening for s in SKELETONS]
        assert len(set(openings)) == len(openings)

    def test_the_pool_offers_genuinely_different_lengths(self):
        # Every clip the same runtime is its own pattern, independent of what
        # happens inside it.
        assert len({s.scenes for s in SKELETONS}) > 1

    def test_an_unused_skeleton_outranks_every_used_one(self):
        recent = [shape("dalil"), shape("hikoya"), shape("teskari")]
        assert choose(recent, "IELTS").name not in {"dalil", "hikoya", "teskari"}

    def test_the_least_recently_used_wins_once_all_are_spent(self):
        # Newest first, so `dalil` at the end is the oldest and comes back up.
        recent = [shape(s.name) for s in SKELETONS][::-1]
        assert choose(recent, "IELTS").name == "dalil"

    def test_the_same_skeleton_is_not_handed_out_twice_running(self):
        recent: list[Shape] = []
        for _ in range(len(SKELETONS)):
            picked = choose(recent, "IELTS")
            assert not recent or picked.name != recent[0].skeleton
            recent.insert(0, shape(picked.name))
        # A full rotation spends the pool rather than favouring a few shapes.
        assert {s.skeleton for s in recent} == {s.name for s in SKELETONS}

    def test_a_first_clip_does_not_get_the_same_shape_for_every_business(self):
        """Empty history is the common case, and the trap.

        Breaking the tie on list order would hand every new client the same
        skeleton — the original bug, one level up.
        """
        picked = {choose([], topic).name for topic in
                  ("IELTS kursi", "backend kursi", "matematika", "bolalar klubi",
                   "ingliz tili", "sertifikat")}
        assert len(picked) > 1


class TestTheGuardCatchesARepeat:
    def test_reusing_a_skeleton_and_its_scene_order_is_rejected(self):
        previous = shape("dalil", "stat", "matn", "royxat", "cta")
        candidate = shape("dalil", "stat", "matn", "royxat", "cta")
        assert too_close(candidate, [previous])

    def test_an_identical_scene_order_is_rejected_under_any_skeleton(self):
        # The viewer sees the cards, not the outline above them.
        previous = shape("dalil", "stat", "matn", "royxat", "cta")
        candidate = shape("savol", "stat", "matn", "royxat", "cta")
        assert too_close(candidate, [previous])

    def test_reusing_a_skeleton_with_a_different_argument_is_allowed(self):
        """The rotation's own output must not be rejected by the guard.

        Six shapes and a queue longer than six means skeletons come back. If
        that alone tripped the guard, every clip past the sixth would burn a
        retry doing exactly what `choose` told it to.
        """
        previous = shape("dalil", "stat", "matn", "royxat", "cta")
        candidate = shape("dalil", "sarlavha", "iqtibos", "taqqoslash", "narx", "cta")
        assert not too_close(candidate, [previous])

    def test_the_guard_looks_back_less_far_than_the_chooser(self):
        older = shape("dalil", "stat", "matn", "royxat", "cta")
        recent = [shape("hikoya"), shape("savol"), shape("qiyos"), older]
        assert len(recent) > GUARD_WINDOW
        # `older` sits outside the window: reusing its shape now is rotation.
        assert not too_close(shape("dalil", "stat", "matn", "royxat", "cta"), recent)

    def test_an_empty_history_never_rejects(self):
        assert not too_close(shape("dalil", "stat", "cta"), [])

    def test_the_complaint_names_what_to_change(self):
        """It goes straight into the retry prompt, so it has to be actionable."""
        previous = shape("dalil", "stat", "matn", "royxat", "cta")
        complaint = too_close(shape("dalil", "stat", "matn", "royxat", "cta"), [previous])
        assert "dalil" in complaint
        assert "boshqacha boshla" in complaint


class TestCloseness:
    def test_scene_order_counts_not_just_which_scenes(self):
        forward = shape("dalil", "stat", "matn", "cta")
        backward = shape("dalil", "cta", "matn", "stat")
        same = shape("dalil", "stat", "matn", "cta")
        assert closeness(same, forward) > closeness(backward, forward)

    def test_a_shared_skeleton_alone_stays_under_the_line(self):
        # Otherwise the rotation cannot reuse a shape without being punished.
        bare = Shape(skeleton="dalil", opening="raqamli ilgak")
        assert closeness(bare, bare) < TOO_CLOSE

    def test_nothing_in_common_scores_zero(self):
        assert closeness(shape("dalil", "stat"), shape("savol", "iqtibos")) == 0.0

    @pytest.mark.parametrize("left,right", [
        (shape("dalil"), shape("dalil", "stat")),
        (shape("dalil", "stat"), shape("dalil")),
    ])
    def test_a_missing_sequence_does_not_crash_the_measure(self, left, right):
        assert 0.0 <= closeness(left, right) <= 1.0


class TestAvoidNote:
    def test_nothing_is_said_when_there_is_no_history(self):
        assert avoid_note([]) == ""

    def test_the_note_names_the_shapes_to_avoid(self):
        note = avoid_note([shape("dalil", "stat", "cta"), shape("hikoya", "matn")])
        assert "dalil" in note and "hikoya" in note

    def test_a_run_of_identical_openings_is_called_out_explicitly(self):
        """The failure this exists for is invisible in a list of names.

        Six clips can carry six skeleton names and still every one of them
        starts by reciting a statistic.
        """
        note = avoid_note([shape("dalil"), shape("dalil"), shape("dalil")])
        assert "bir xil boshlangan" in note

    def test_mixed_openings_draw_no_warning(self):
        note = avoid_note([shape("dalil"), shape("hikoya")])
        assert "bir xil boshlangan" not in note


class TestTheAgentUsesIt:
    """The wiring, end to end: history in, a differently-shaped clip out."""

    @staticmethod
    def _plan(*uses: str):
        from app.agents.promo_brief import BriefPlan, BriefScene, SceneCopy

        copy = {"matn": {}, "stat": {"title": "Xarajat", "to": 68},
                "cta": {"title": "Yozing"}}
        return BriefPlan.model_construct(mood="tezkor", scenes=[
            BriefScene(use=use, say="Bir *ikki* uch to'rt besh olti.",
                       text=SceneCopy(**copy[use]))
            for use in uses
        ])

    async def _write(self, monkeypatch, history: list[Shape], *, topic="IELTS",
                     uses=("matn", "stat", "cta"), scenes: int = 0,
                     backdrop: str = ""):
        from app.agents.promo_brief import PromoBriefAgent
        from tests.test_agents import make_business, make_knowledge

        agent = PromoBriefAgent(session=None)
        prompts: list[str] = []

        async def fake_ask_json(prompt, schema, **kwargs):
            prompts.append(prompt)
            return self._plan(*uses)

        async def fake_recent(business):
            return history

        monkeypatch.setattr(agent, "ask_json", fake_ask_json)
        monkeypatch.setattr(agent, "_recent", fake_recent)
        # `_library` draws a six-image set on a cold shelf; a unit test has
        # no business writing into the media root to check a prompt.
        monkeypatch.setattr(agent, "_library",
                            lambda business, knowledge: [backdrop] if backdrop else [])
        written = await agent.write(make_business(), make_knowledge(), topic,
                                    scenes=scenes)
        return written, prompts

    async def test_the_chosen_skeleton_reaches_the_model(self, monkeypatch):
        written, prompts = await self._write(monkeypatch, [])
        assert written.shape.skeleton
        assert f"«{written.shape.skeleton}» skeleti" in prompts[0]

    async def test_history_pushes_the_clip_onto_a_different_skeleton(self, monkeypatch):
        written, prompts = await self._write(monkeypatch, [shape("dalil")])
        assert written.shape.skeleton != "dalil"
        # And the model is told what not to repeat, not just handed a new shape.
        assert "TAKRORLAMA" in prompts[0] and "dalil" in prompts[0]

    async def test_the_length_follows_the_skeleton_when_nobody_asked(self, monkeypatch):
        from app.services.promo_variety import BY_NAME

        written, prompts = await self._write(monkeypatch, [])
        wanted = BY_NAME[written.shape.skeleton].scenes
        assert f"Jami {wanted} ta sahna" in prompts[0]

    async def test_an_explicit_length_still_wins(self, monkeypatch):
        _, prompts = await self._write(monkeypatch, [], scenes=5)
        assert "Jami 5 ta sahna" in prompts[0]

    async def test_a_repeat_of_the_last_clip_is_sent_back(self, monkeypatch):
        # The fake model returns this exact sequence every time, and it is what
        # the business shipped last — an identical scene order under any beats.
        history = [shape("dalil", "matn", "stat", "cta")]
        _, prompts = await self._write(monkeypatch, history)
        assert len(prompts) > 1
        assert "OLDINGI URINISH XATOSI" in prompts[1]
        assert "juda o'xshab qoldi" in prompts[1]

    async def test_a_stubborn_model_still_gets_a_clip_out(self, monkeypatch):
        """A worse clip beats no clip — the owner is waiting on a render."""
        from app.agents.promo_brief import ATTEMPTS

        history = [shape("dalil", "matn", "stat", "cta")]
        written, prompts = await self._write(monkeypatch, history)
        assert len(prompts) == ATTEMPTS
        assert written.script["scenes"]

    async def test_the_shape_travels_back_for_the_caller_to_record(self, monkeypatch):
        from app.services.promo_variety import BY_NAME

        written, _ = await self._write(monkeypatch, [],
                                       backdrop="/brand/x/photos/bg_02_server.jpg")
        assert written.shape.archetypes == ("matn", "stat", "cta")
        # The skeleton's mood, not the model's: the feel belongs to the shape.
        assert written.shape.mood == BY_NAME[written.shape.skeleton].mood
        # A filename, not the path it was read from.
        assert written.shape.backdrop == "bg_02_server.jpg"


class TestTheLookAndSoundMoveToo:
    """Three more constants that sat on top of working machinery.

    `template.html` implements five transitions and five entries; every
    archetype declared `cut` and none set `entry`. `_music` reads a `bpm`
    nothing wrote, so every clip ran at 118. `backdrops.py` draws six motifs
    and the composer never set `background`. All three were built, wired into
    the renderer, and pinned — the same failure as the outline, three times.
    """

    def test_every_skeleton_names_motion_the_template_implements(self):
        # A value outside these falls through to the template's default, which
        # renders — silently, as something other than what was asked for.
        transitions = {"cut", "none", "slide", "wipe", "whip"}
        entries = {"rise", "scale", "slideX", "flip", "mask"}
        for s in SKELETONS:
            assert s.transition in transitions, s.name
            assert s.entry in entries, s.name

    def test_no_two_skeletons_move_the_same_way(self):
        pairs = [(s.transition, s.entry) for s in SKELETONS]
        assert len(set(pairs)) == len(pairs)

    def test_tempo_is_no_longer_one_number(self):
        tempos = {s.bpm for s in SKELETONS}
        assert len(tempos) > 3
        assert 118 not in tempos or len(tempos) > 1

    def test_every_skeleton_mood_maps_to_a_bed_that_exists(self):
        from app.services.music import MOODS as BEDS
        from app.services.promo_scenes import MOODS

        for s in SKELETONS:
            assert s.mood in MOODS, f"{s.name}: «{s.mood}» promo_scenes.MOODS da yo'q"
            assert MOODS[s.mood] in BEDS, s.name

    def test_all_four_synthesised_beds_are_reachable(self):
        """`tense` existed in music.py and nothing could name it."""
        from app.services.music import MOODS as BEDS
        from app.services.promo_scenes import MOODS

        assert set(MOODS.values()) == set(BEDS)


class TestTheScriptCarriesThem:
    """The composer's output is what the browser actually reads."""

    @staticmethod
    def _script(**job_extra):
        from app.services.promo_families import Brand
        from app.services.promo_scenes import build_script

        job = {
            "name": "sinov", "mood": "tezkor", "scenes": [
                {"use": "matn", "slot": "s0", "say": 0},
                {"use": "cta", "slot": "s1", "say": 1},
            ],
            "say": ["Bir ikki uch to'rt besh.", "Olti yetti sakkiz."],
            "text": {"s0": {}, "s1": {"headline": "Yozing"}},
            **job_extra,
        }
        return build_script(job, Brand.from_colors({}, mark="Sinov", cta="Yozing"))

    def test_motion_reaches_the_script(self):
        script = self._script(transition="slide", entry="flip")
        assert script["transition"] == "slide"
        assert script["entry"] == "flip"

    def test_tempo_reaches_the_script(self):
        assert self._script(bpm=126)["music"]["bpm"] == 126

    def test_a_backdrop_reaches_the_script(self):
        script = self._script(background="/brand/x/photos/bg_03_network.jpg")
        assert script["background"].endswith("bg_03_network.jpg")

    def test_a_job_that_says_nothing_renders_as_it_always_did(self):
        """Every lab preset and every old job goes through this path."""
        script = self._script()
        assert script["transition"] == "cut"
        assert script["entry"] == "rise"
        assert "background" not in script
        assert script["music"]["bpm"] == 118

    def test_the_new_mood_reaches_the_tense_bed(self):
        assert self._script(mood="keskin")["music"]["mood"] == "tense"


class TestBackdropRotation:
    LIB: ClassVar[list[str]] = ["bg_01_ui.jpg", "bg_02_server.jpg", "bg_03_network.jpg"]

    def test_an_empty_shelf_is_not_an_error(self):
        from app.services.promo_variety import choose_backdrop

        assert choose_backdrop([], []) == ""

    def test_consecutive_clips_do_not_repeat_a_picture(self):
        from app.services.promo_variety import choose_backdrop

        history: list[Shape] = []
        for _ in range(len(self.LIB)):
            picked = choose_backdrop(history, self.LIB)
            assert not history or picked != history[0].backdrop
            history.insert(0, Shape(backdrop=picked))
        assert {s.backdrop for s in history} == set(self.LIB)

    def test_it_rotates_on_its_own_axis_not_the_skeletons(self):
        """Tying the picture to the shape would make every shape repeat look
        like a total repeat — same beats, same background, same clip."""
        from app.services.promo_variety import choose_backdrop

        history = [Shape(skeleton="dalil", backdrop="bg_01_ui.jpg")]
        assert choose_backdrop(history, self.LIB) != "bg_01_ui.jpg"
