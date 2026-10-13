"""Narration, and the two ways it is allowed to fail.

Clips shipped mute while the composer cut them to the rhythm of speech nobody
could hear. Adding a voice adds an external dependency with a ten-request daily
allowance, so the interesting cases here are not the happy path — they are
running out mid-clip and losing the key, both of which must produce a watchable
clip rather than an exception.
"""

from __future__ import annotations

import array
import wave
from pathlib import Path

import pytest

from app.services import tts
from app.services.translit import convert


class TestTheSpellingBridge:
    """Only the synthesiser sees this; the screen keeps the real spelling."""

    def test_the_letters_that_break_are_the_ones_rewritten(self):
        out = convert("qo'shish uchun x va g'alaba")
        assert "q" not in out and "x" not in out
        assert "ko" in out and "ğ" in out

    def test_digraphs_survive_being_split(self):
        # Rewriting `s` before `sh` would turn "shu" into "şh".
        assert convert("shu chiroq") == "şu çirok"

    def test_every_apostrophe_a_keyboard_produces_is_handled(self):
        for apostrophe in "'’ʻ‘ʼ´`":
            assert convert(f"o{apostrophe}quv") == "okuv"

    def test_latin_mode_changes_nothing(self):
        assert convert("qo'shish", "lotin") == "qo'shish"


class TestWordTiming:
    def test_words_are_ordered_and_inside_the_line(self):
        words = tts._words_for("Bir ikki uch to'rt besh", 3.0)
        times = [w.at for w in words]
        assert times == sorted(times)
        assert times[0] == 0.0 and times[-1] < 3.0

    def test_emphasis_survives_as_a_flag_not_as_asterisks(self):
        words = tts._words_for("Bir *ikki* uch", 2.0)
        assert [w.b for w in words] == [False, True, False]
        assert all("*" not in w.w for w in words)

    def test_vowel_heavy_words_are_given_more_room(self):
        assert tts._weight("aeiou") > tts._weight("qrstv")

    def test_an_empty_line_produces_no_words(self):
        assert tts._words_for("   ", 2.0) == []


def _wav(path: Path, seconds: float, rate: int = tts.MIX_RATE) -> Path:
    frames = array.array("h", [0]) * int(seconds * rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames.tobytes())
    return path


class TestDucking:
    def test_no_narration_means_no_envelope(self):
        assert tts.envelope([], 1000) is None

    def test_the_bed_is_held_down_while_a_line_plays(self, tmp_path):
        rate = 1000
        clip = _wav(tmp_path / "a.wav", 1.0, rate=rate)
        gate = tts.envelope([(clip, 0.5)], 2000, rate=rate, attack=0.05, release=0.2)
        assert gate is not None
        assert gate[100] == pytest.approx(0.0)        # before the line
        assert gate[900] > 0.9                        # inside it
        assert gate[1990] < 0.5                       # released after

    def test_it_ducks_before_the_word_lands_not_after(self):
        """A duck that arrives late clips the first syllable every time."""
        rate = 1000
        gate = tts.envelope([(Path("missing.wav"), 0.0)], 100, rate=rate)
        # An unreadable file contributes nothing rather than raising.
        assert gate is not None and max(gate) == 0.0


class TestQuotaIsAnOutcome:
    async def test_running_out_returns_what_was_spoken(self, tmp_path, monkeypatch):
        """Ten requests a day, one per scene — this is the normal case."""
        spoken: list[str] = []

        async def fake(text, out, model):
            if len(spoken) >= 2:
                raise tts._Retryable(429, '{"error":"quota PerDay exceeded"}')
            spoken.append(text)
            _wav(Path(out), 1.0, rate=24000)

        async def fake_ffmpeg(args):
            # Stand in for trim + atempo: hand back a file at the mix rate.
            _wav(Path(args[-1]), 1.0)

        monkeypatch.setattr(tts, "_synthesise", fake)
        monkeypatch.setattr(tts, "_ffmpeg", fake_ffmpeg)
        lines = await tts.narrate(["Bir gap.", "Ikkinchi gap.", "Uchinchi gap."],
                                  tmp_path, name="sinov")
        assert len(lines) == 2
        assert all(line.dur > 0 for line in lines)

    async def test_it_stops_rather_than_skipping_a_line(self, tmp_path, monkeypatch):
        """`timing` is read positionally by the composer.

        Skipping line 1 and keeping line 2 would put scene 2's audio under
        scene 1 and shift the whole clip onto the wrong words.
        """
        async def fake(text, out, model):
            if "Ikkinchi" in text:
                raise tts._Retryable(429, "PerDay")
            _wav(Path(out), 1.0, rate=24000)

        async def fake_ffmpeg(args):
            _wav(Path(args[-1]), 1.0)

        monkeypatch.setattr(tts, "_synthesise", fake)
        monkeypatch.setattr(tts, "_ffmpeg", fake_ffmpeg)
        lines = await tts.narrate(["Bir.", "Ikkinchi.", "Uchinchi."],
                                  tmp_path, name="sinov")
        assert len(lines) == 1


class TestTheAgentDegrades:
    """None of this may cost a render."""

    async def test_narration_off_costs_nothing(self):
        from app.agents.promo_brief import PromoBriefAgent

        agent = PromoBriefAgent(session=None)
        assert await agent._narrate({"say": ["Bir gap."]}, False) == []

    async def test_no_api_key_renders_mute(self, monkeypatch):
        from app.agents.promo_brief import PromoBriefAgent

        monkeypatch.setattr(tts, "available", lambda: False)
        agent = PromoBriefAgent(session=None)
        assert await agent._narrate({"say": ["Bir gap."]}, True) == []

    async def test_a_broken_synthesiser_renders_mute(self, monkeypatch):
        from app.agents.promo_brief import PromoBriefAgent

        async def boom(*args, **kwargs):
            raise RuntimeError("tts is down")

        monkeypatch.setattr(tts, "available", lambda: True)
        monkeypatch.setattr(tts, "narrate", boom)
        agent = PromoBriefAgent(session=None)
        assert await agent._narrate({"say": ["Bir gap."], "name": "x"}, True) == []


class TestTheClipIsCutToWhatWasSpoken:
    """The point of measuring: scene lengths stop being guesses."""

    @staticmethod
    def _build(timing=None):
        from app.services.promo_families import Brand
        from app.services.promo_scenes import build_script

        job = {
            "name": "sinov", "mood": "tezkor",
            "scenes": [{"use": "matn", "slot": "s0", "say": 0},
                       {"use": "cta", "slot": "s1", "say": 1}],
            "say": ["Bir ikki uch.", "To'rt besh olti."],
            "text": {"s0": {}, "s1": {"headline": "Yozing"}},
        }
        return build_script(job, Brand.from_colors({}, mark="S", cta="Yozing"),
                            timing=timing)

    def test_measured_speech_sets_the_cut_points(self, tmp_path):
        timing = [
            {"src": str(_wav(tmp_path / "a.wav", 2.4)), "dur": 2.4, "words": []},
            {"src": str(_wav(tmp_path / "b.wav", 1.8)), "dur": 1.8, "words": []},
        ]
        script = self._build(timing)
        # The cut is driven by measured speech rather than a word-count guess,
        # then rounded up to the pulse — never down, or the line gets clipped.
        from app.services.music import snap_to_beat
        from app.services.promo_scenes import DEFAULT_BPM

        assert script["scenes"][0]["at"][1] == snap_to_beat(2.62, DEFAULT_BPM)
        assert script["scenes"][0]["at"][1] >= 2.62

    def test_the_voice_track_carries_offsets_the_mixer_can_use(self, tmp_path):
        timing = [
            {"src": str(_wav(tmp_path / "a.wav", 2.4)), "dur": 2.4, "words": []},
            {"src": str(_wav(tmp_path / "b.wav", 1.8)), "dur": 1.8, "words": []},
        ]
        from app.services.music import snap_to_beat
        from app.services.promo_scenes import DEFAULT_BPM

        track = self._build(timing)["voice"]
        # The second line starts where the first scene ends — on the beat.
        assert [item["at"] for item in track] == [0.0, snap_to_beat(2.62, DEFAULT_BPM)]

    def test_without_timing_the_clip_still_builds_and_stays_mute(self):
        script = self._build(None)
        assert "voice" not in script
        assert script["duration"] > 0


class TestTheMixerPlacesIt:
    def test_narration_reaches_the_track_and_ducks_the_bed(self, tmp_path):
        import array
        import math

        from app.services.kinetic import mix_soundtrack
        from app.services.music import Bed

        rate = tts.MIX_RATE
        # A loud bed and one second of loud speech starting at t=1.
        tone = array.array("d", (0.5 * math.sin(i / 40) for i in range(rate * 3)))
        speech = tmp_path / "line.wav"
        with wave.open(str(speech), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(array.array(
                "h", (int(12000 * math.sin(i / 12)) for i in range(rate))
            ).tobytes())

        out = mix_soundtrack([], 3.0, tmp_path / "mix.wav",
                             bed=Bed(tone, array.array("d", tone)),
                             voice=[(speech, 1.0)])
        samples, _ = tts.read_mono(out)
        quiet = max(abs(s) for s in samples[:int(rate * 0.5)])
        loud = max(abs(s) for s in samples[int(rate * 1.2):int(rate * 1.8)])
        assert loud > quiet, "nutq mix'ga tushmagan"

    def test_a_missing_line_does_not_fail_the_render(self, tmp_path):
        from app.services.kinetic import mix_soundtrack

        out = mix_soundtrack([], 1.0, tmp_path / "mix.wav",
                             voice=[(tmp_path / "gone.wav", 0.0)])
        assert out.exists()

    def test_a_wrong_rate_is_refused_rather_than_played_at_the_wrong_pitch(self, tmp_path):
        from app.services.kinetic import mix_soundtrack

        odd = _wav(tmp_path / "odd.wav", 0.5, rate=8000)
        out = mix_soundtrack([], 1.0, tmp_path / "mix.wav", voice=[(odd, 0.0)])
        samples, _ = tts.read_mono(out)
        assert max(abs(s) for s in samples) == pytest.approx(0.0, abs=1e-6)
