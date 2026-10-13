"""The owner's own voice as the input the edit is cut to.

Synthesis was never the point; measured delivery was. The composer cuts scenes
to whatever audio it is given, so handing it a real take gets the same
beat-locked precision with a real person speaking — and spends none of the ten
requests a day the free tier allows.

The one thing that must not carry over from synthesis is the tempo correction.
A model reads at whatever pace it likes and is stretched to hit `TARGET_WPM`; a
person's pace is the take, and speeding it up would be editing the performance
to match a number.
"""

from __future__ import annotations

import array
import math
import wave
from pathlib import Path

import pytest

from app.services import tts


def tone(path: Path, seconds: float, *, rate: int = tts.MIX_RATE,
         amplitude: int = 9000) -> Path:
    frames = array.array("h", (int(amplitude * math.sin(i / 14))
                               for i in range(int(seconds * rate))))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames.tobytes())
    return path


def take(path: Path, spans: list[float], gap: float = 0.8) -> Path:
    """A single recording: spoken spans separated by real pauses."""
    rate = tts.MIX_RATE
    frames = array.array("h")
    for index, span in enumerate(spans):
        if index:
            frames.extend([0] * int(gap * rate))
        frames.extend(int(9000 * math.sin(i / 14)) for i in range(int(span * rate)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames.tobytes())
    return path


class TestMeasuringWhatSomebodyRecorded:
    async def test_each_line_gets_its_own_measured_length(self, tmp_path):
        paths = [tone(tmp_path / f"{i}.wav", d) for i, d in enumerate((1.4, 2.1))]
        lines = await tts.measure(paths, ["Bir ikki.", "Uch to'rt besh."],
                                  tmp_path / "out")
        assert len(lines) == 2
        assert lines[0].dur == pytest.approx(1.4, abs=0.15)
        assert lines[1].dur == pytest.approx(2.1, abs=0.15)

    async def test_word_timings_come_back_for_karaoke(self, tmp_path):
        paths = [tone(tmp_path / "0.wav", 2.0)]
        lines = await tts.measure(paths, ["Bir *ikki* uch"], tmp_path / "out")
        words = lines[0].words
        assert [w.w for w in words] == ["Bir", "ikki", "uch"]
        assert [w.b for w in words] == [False, True, False]

    async def test_a_half_recorded_script_renders_the_rest_silent(self, tmp_path):
        """The composer estimates a line with no timing; it does not fail."""
        paths = [tone(tmp_path / "0.wav", 1.2)]
        lines = await tts.measure(paths, ["Bir.", "Ikki.", "Uch."], tmp_path / "out")
        assert len(lines) == 1

    async def test_the_delivery_is_not_sped_up_to_hit_a_number(self, tmp_path):
        """A person's pace is the performance, not an artefact to correct."""
        slow = tone(tmp_path / "0.wav", 4.0)
        lines = await tts.measure([slow], ["Bir ikki"], tmp_path / "out")
        # Two words in four seconds is 30 wpm against a 150 wpm target. If the
        # tempo correction had carried over, this would come back near 0.8s.
        assert lines[0].dur == pytest.approx(4.0, abs=0.2)

    async def test_the_audio_is_handed_over_at_the_mix_rate(self, tmp_path):
        paths = [tone(tmp_path / "0.wav", 1.0, rate=22050)]
        lines = await tts.measure(paths, ["Bir ikki."], tmp_path / "out")
        _, rate = tts.read_mono(Path(lines[0].src))
        assert rate == tts.MIX_RATE


class TestSplittingOneTakeIntoLines:
    """Nobody records nine separate files; people read the script once."""

    async def test_a_take_is_cut_at_its_pauses(self, tmp_path):
        source = take(tmp_path / "take.wav", [1.5, 2.0, 1.2])
        lines = await tts.split(source, ["Bir.", "Ikki.", "Uch."], tmp_path / "out")
        assert len(lines) == 3
        assert [round(line.dur, 1) for line in lines] == [
            pytest.approx(1.5, abs=0.4),
            pytest.approx(2.0, abs=0.4),
            pytest.approx(1.2, abs=0.4),
        ]

    async def test_the_longest_pauses_are_the_line_breaks(self, tmp_path):
        source = take(tmp_path / "take.wav", [1.0, 1.0, 1.0, 1.0])
        lines = await tts.split(source, ["Bir.", "Ikki.", "Uch.", "To'rt."],
                                tmp_path / "out")
        assert len(lines) == 4
        assert all(line.dur > 0.4 for line in lines)

    async def test_a_take_with_too_few_pauses_says_so(self, tmp_path):
        """Guessing a split inside a sentence cuts somebody off mid-word."""
        source = take(tmp_path / "take.wav", [2.0, 2.0])
        with pytest.raises(ValueError, match="pauza"):
            await tts.split(source, ["Bir.", "Ikki.", "Uch.", "To'rt."],
                            tmp_path / "out")

    async def test_a_single_line_script_needs_no_splitting(self, tmp_path):
        source = tone(tmp_path / "take.wav", 2.0)
        lines = await tts.split(source, ["Bir ikki uch."], tmp_path / "out")
        assert len(lines) == 1


class TestTheAgentPrefersARealVoice:
    @staticmethod
    def _job(says):
        return {"name": "own-test", "say": says}

    async def test_a_recording_is_used_instead_of_the_synthesiser(self, tmp_path, monkeypatch):
        from app.agents.promo_brief import PromoBriefAgent

        synthesised = False

        async def never(*args, **kwargs):
            nonlocal synthesised
            synthesised = True
            return []

        monkeypatch.setattr(tts, "narrate", never)
        source = take(tmp_path / "take.wav", [1.2, 1.4])
        agent = PromoBriefAgent(session=None)
        timing = await agent._narrate(self._job(["Bir.", "Ikki."]), True, str(source))
        assert len(timing) == 2
        assert not synthesised, "yozuv bor bo'lsa TTS chaqirilmasligi kerak"

    async def test_a_mismatched_take_does_not_get_synthesised_over(self, tmp_path, monkeypatch):
        """Quietly speaking over somebody's recording hides the real problem."""
        from app.agents.promo_brief import PromoBriefAgent

        async def never(*args, **kwargs):
            raise AssertionError("TTS chaqirilmasligi kerak edi")

        monkeypatch.setattr(tts, "narrate", never)
        source = take(tmp_path / "take.wav", [2.0])
        agent = PromoBriefAgent(session=None)
        timing = await agent._narrate(self._job(["Bir.", "Ikki.", "Uch."]), True,
                                      str(source))
        assert timing == []

    async def test_without_a_recording_the_synthesiser_still_runs(self, tmp_path, monkeypatch):
        from app.agents.promo_brief import PromoBriefAgent

        called = False

        async def fake(says, out_dir, **kwargs):
            nonlocal called
            called = True
            return []

        monkeypatch.setattr(tts, "available", lambda: True)
        monkeypatch.setattr(tts, "narrate", fake)
        agent = PromoBriefAgent(session=None)
        await agent._narrate(self._job(["Bir."]), True, None)
        assert called
