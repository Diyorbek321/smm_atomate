"""The edit plan: repaired as before, but no longer repaired in silence.

`_sanitise` has always fixed what a model gets wrong — reversed pairs, overlaps,
timestamps past the end of the file, a plan longer than the format allows. It
fixed them without a word, so a plan that arrived needing six of its eight
segments discarded was quietly reduced to two and shipped, and the edit the
owner received was the repair rather than anything anyone chose.

These lock the reporting and the rewrite it feeds. The repairs themselves are
unchanged; what is new is that the model is told, and asked again.
"""

from __future__ import annotations

from app.agents.video_editor import (
    ATTEMPTS,
    MAX_CLIP_SECONDS,
    EditPlan,
    KeepSegment,
    VideoEditorAgent,
    VideoEditRequest,
)
from tests.test_agents import make_business


def seg(start: float, end: float, why: str = "") -> KeepSegment:
    return KeepSegment(start=start, end=end, why=why)


def sanitise(segments, duration=120.0, **plan_kwargs):
    plan = EditPlan(keep=list(segments), **plan_kwargs)
    return VideoEditorAgent._sanitise(plan, duration)


class TestTheRepairsStillHappen:
    def test_a_segment_past_the_end_of_the_file_is_dropped(self):
        plan, _ = sanitise([seg(0, 5), seg(200, 260)], duration=60.0)
        assert [(s.start, s.end) for s in plan.keep] == [(0.0, 5.0)]

    def test_overlaps_do_not_repeat_speech(self):
        plan, _ = sanitise([seg(0, 10), seg(5, 20)])
        assert plan.keep[1].start >= plan.keep[0].end

    def test_reversed_order_is_sorted(self):
        plan, _ = sanitise([seg(30, 40), seg(0, 10)])
        assert [s.start for s in plan.keep] == [0.0, 30.0]

    def test_a_plan_longer_than_the_format_is_trimmed(self):
        plan, _ = sanitise([seg(i * 20, i * 20 + 20) for i in range(6)], duration=200.0)
        assert plan.total_seconds <= MAX_CLIP_SECONDS


class TestItNowSaysWhatItRepaired:
    def test_a_clean_plan_draws_no_complaint(self):
        plan, complaints = sanitise([seg(0, 10), seg(20, 30)])
        assert complaints == []
        assert plan.is_usable

    def test_out_of_range_segments_are_reported(self):
        _, complaints = sanitise([seg(0, 5), seg(200, 260)], duration=60.0)
        assert any("chegarasidan tashqarida" in c for c in complaints)

    def test_overlaps_are_reported(self):
        _, complaints = sanitise([seg(0, 10), seg(5, 20), seg(18, 30)])
        assert any("ustiga tushdi" in c for c in complaints)

    def test_being_over_length_is_reported(self):
        _, complaints = sanitise([seg(i * 20, i * 20 + 20) for i in range(6)],
                                 duration=200.0)
        assert any("soniyadan uzun" in c for c in complaints)

    def test_an_empty_plan_is_reported(self):
        _, complaints = sanitise([])
        assert any("yaroqli bo'lak qolmadi" in c for c in complaints)

    def test_losing_most_of_the_plan_is_reported_as_a_bad_plan(self):
        """Losing one segment is ordinary; losing most means the model did not
        understand the transcript, and repairing that designs the edit for it."""
        segments = [seg(0, 5)] + [seg(500 + i, 505 + i) for i in range(5)]
        _, complaints = sanitise(segments, duration=60.0)
        assert any("mos kelmadi" in c for c in complaints)


class TestJudgementsNotJustRepairs:
    def test_handing_back_the_whole_file_is_not_an_edit(self):
        _, complaints = sanitise([seg(0, 59)], duration=60.0)
        assert any("montaj emas" in c for c in complaints)

    def test_a_genuine_single_segment_edit_is_accepted(self):
        # Half the source kept is a decision, not an echo.
        _, complaints = sanitise([seg(10, 40)], duration=120.0)
        assert complaints == []

    def test_a_hook_pointing_at_dropped_material_is_refused(self):
        """Range-checking against the file was never enough."""
        plan, complaints = sanitise([seg(0, 10)], duration=120.0, hook_at=80.0)
        assert plan.hook_at is None
        assert any("hook_at" in c for c in complaints)

    def test_a_hook_inside_a_kept_segment_survives(self):
        plan, complaints = sanitise([seg(0, 10)], duration=120.0, hook_at=4.0)
        assert plan.hook_at == 4.0
        assert complaints == []


class TestItAsksAgain:
    @staticmethod
    async def _run(monkeypatch, plans: list[EditPlan]):
        agent = VideoEditorAgent(session=None)
        prompts: list[str] = []
        handed = iter(plans)

        async def fake_ask_json(prompt, schema, **kwargs):
            prompts.append(prompt)
            return next(handed, plans[-1])

        monkeypatch.setattr(agent, "ask_json", fake_ask_json)
        request = VideoEditRequest(
            business=make_business(),
            segments=[{"start": 0.0, "end": 5.0, "text": "Bir ikki uch."},
                      {"start": 5.0, "end": 9.0, "text": "To'rt besh."}],
            duration=60.0,
        )
        return await agent.run(request), prompts

    async def test_a_clean_plan_is_not_second_guessed(self, monkeypatch):
        good = EditPlan(keep=[seg(0, 10), seg(20, 30)])
        plan, prompts = await self._run(monkeypatch, [good])
        assert len(prompts) == 1
        assert plan.is_usable

    async def test_a_broken_plan_is_sent_back_with_reasons(self, monkeypatch):
        broken = EditPlan(keep=[seg(0, 59)])                  # the whole file
        good = EditPlan(keep=[seg(0, 10), seg(20, 30)])
        plan, prompts = await self._run(monkeypatch, [broken, good])
        assert len(prompts) == 2
        assert "OLDINGI URINISH XATOSI" in prompts[1]
        assert "montaj emas" in prompts[1]
        assert [(s.start, s.end) for s in plan.keep] == [(0.0, 10.0), (20.0, 30.0)]

    async def test_a_stubborn_model_still_yields_an_edit(self, monkeypatch):
        """A repaired edit is worse. No edit is worse still — the owner is
        waiting on a clip either way."""
        broken = EditPlan(keep=[seg(0, 59)])
        plan, prompts = await self._run(monkeypatch, [broken, broken])
        assert len(prompts) == ATTEMPTS
        assert plan.is_usable

    async def test_a_dead_model_falls_back_to_silence_trimming(self, monkeypatch):
        agent = VideoEditorAgent(session=None)

        async def boom(*args, **kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr(agent, "ask_json", boom)
        plan = await agent.run(VideoEditRequest(
            business=make_business(),
            segments=[{"start": 0.0, "end": 5.0, "text": "Bir."}],
            duration=60.0))
        assert not plan.is_usable          # the caller keeps its own trim

    async def test_an_empty_transcript_never_reaches_the_model(self, monkeypatch):
        agent = VideoEditorAgent(session=None)
        called = False

        async def fake(*args, **kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr(agent, "ask_json", fake)
        plan = await agent.run(VideoEditRequest(business=make_business(),
                                                segments=[], duration=60.0))
        assert not called and not plan.is_usable
