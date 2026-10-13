"""What a dialogue engineer does to a phone recording, as one ffmpeg chain.

Adobe Audition cannot be driven from a container, and the argument for trying
was never really about Audition — it was about the audio being untreated. It
was: the footage path denoised, high-passed and normalised, and the narration
path did nothing at all but trim silence. A voice recorded on a phone in a room
went into the clip exactly as the phone heard it.

None of this needs a model. "High-pass at 80 Hz" is a constant a sound engineer
writes once, not a judgement; putting an agent in that loop buys latency and
variance for nothing. So it is a chain, and these tests hold its shape.
"""

from __future__ import annotations

import array
import math
import wave
from pathlib import Path

import pytest

from app.services import tts


def noisy(path: Path, seconds: float = 2.0, *, tone: float = 0.30,
          hiss: float = 0.05, rate: int = tts.MIX_RATE) -> Path:
    """A quiet voice-like tone under a layer of hiss — a phone in a room."""
    import random

    rng = random.Random(7)
    frames = array.array("h", (
        int(32767 * (tone * math.sin(i / 14) + hiss * (rng.random() * 2 - 1)))
        for i in range(int(seconds * rate))
    ))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames.tobytes())
    return path


def level(path: Path) -> float:
    """Mean absolute level of a file, 0.0 – 1.0."""
    samples, _ = tts.read_mono(path)
    return sum(abs(s) for s in samples) / max(1, len(samples))


class TestTheChainIsShaped:
    def test_every_step_a_dialogue_engineer_would_run(self):
        for step in ("highpass", "afftdn", "deesser", "acompressor",
                     "alimiter", "loudnorm", "equalizer"):
            assert step in tts.VOICE_CHAIN, step

    def test_denoise_runs_before_compression(self):
        """Compression raises the noise floor with the voice: hiss that was
        inaudible becomes the loudest thing in a pause."""
        chain = tts.VOICE_CHAIN
        assert chain.index("afftdn") < chain.index("acompressor")

    def test_the_de_esser_runs_after_the_presence_lift(self):
        """That lift is what makes sibilance sharp enough to need taming."""
        chain = tts.VOICE_CHAIN
        assert chain.index("f=3500") < chain.index("deesser")

    def test_the_limiter_runs_after_the_make_up_gain(self):
        chain = tts.VOICE_CHAIN
        assert chain.index("acompressor") < chain.index("alimiter")

    def test_it_normalises_below_the_master_target(self):
        """Per-line loudnorm makes the lines agree with each other; the master
        pass sets the final level and needs room to work in."""
        from app.services.encoding import LOUDNESS_TARGET

        assert "I=-18" in tts.VOICE_CHAIN
        # Quieter than the master target, so the master pass has somewhere to
        # go. Louder, and it would be fighting the mix it feeds.
        assert LOUDNESS_TARGET > -18


class TestItActuallyTreatsTheAudio:
    async def test_a_quiet_noisy_take_comes_back_levelled(self, tmp_path):
        source = noisy(tmp_path / "raw.wav", tone=0.10, hiss=0.04)
        out = tmp_path / "fixed.wav"
        await tts._normalise(source, out, enhance=True)
        assert level(out) > level(source) * 1.5, "daraja ko'tarilmadi"

    async def test_without_the_flag_the_audio_is_left_alone(self, tmp_path):
        """Synthesised speech arrives clean, level and roomless. Denoising it
        removes detail to fix a problem it does not have."""
        source = noisy(tmp_path / "raw.wav", tone=0.30, hiss=0.0)
        out = tmp_path / "plain.wav"
        await tts._normalise(source, out, enhance=False)
        assert level(out) == pytest.approx(level(source), rel=0.25)


class TestWhichPathGetsIt:
    async def test_a_recording_is_treated(self, tmp_path, monkeypatch):
        seen: list[bool] = []

        async def spy(source, target, start=None, end=None, *, enhance=False,
                      preset=""):
            seen.append(enhance)
            noisy(Path(target), 1.0)

        monkeypatch.setattr(tts, "_normalise", spy)
        await tts.measure([noisy(tmp_path / "a.wav")], ["Bir gap."], tmp_path / "out")
        assert seen == [True]

    async def test_synthesised_speech_is_not(self, tmp_path, monkeypatch):
        """`narrate` runs its own atempo pass and must stay untreated."""
        calls: list[list[str]] = []

        async def fake_ffmpeg(args):
            calls.append(args)
            noisy(Path(args[-1]), 1.0)

        async def fake_synth(text, out, *a, **k):
            noisy(Path(out), 1.0, rate=24000)
            return "model"

        monkeypatch.setattr(tts, "_ffmpeg", fake_ffmpeg)
        monkeypatch.setattr(tts, "_synthesise_with_fallback", fake_synth)
        await tts.narrate(["Bir gap."], tmp_path / "out", name="t")
        assert calls, "ffmpeg umuman chaqirilmadi"
        assert not any("acompressor" in " ".join(args) for args in calls)


class TestThePresetIsMeasuredNotAsked:
    """Which chain a take needs is in the numbers, so nothing asks a model.

    A language model cannot hear. Given these figures it would be guessing at
    a threshold somebody already knows, more slowly and less consistently —
    the decision is real, but it is arithmetic, not judgement.
    """

    @staticmethod
    def take(path: Path, noise: float, seconds: float = 4.0) -> Path:
        """Speech-and-pause material: bursts of tone over a constant floor."""
        import random

        rate, rng = tts.MIX_RATE, random.Random(11)
        frames = array.array("h")
        for i in range(int(seconds * rate)):
            speaking = (i / rate) % 1.6 < 1.0
            tone = 0.32 * math.sin(i / 14) if speaking else 0.0
            frames.append(int(32767 * max(-0.99, min(0.99,
                tone + noise * (rng.random() * 2 - 1)))))
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(frames.tobytes())
        return path

    @pytest.mark.parametrize("noise,expected", [
        (0.0005, "tinch"),
        (0.02, "xona"),
        (0.12, "shovqin"),
    ])
    async def test_a_room_is_recognised_from_its_pauses(self, tmp_path, noise, expected):
        reading = await tts.analyse(self.take(tmp_path / "t.wav", noise))
        assert tts.preset_for(reading) == expected, reading.snr

    async def test_the_signal_to_noise_falls_as_the_room_gets_worse(self, tmp_path):
        quiet = await tts.analyse(self.take(tmp_path / "a.wav", 0.0005))
        loud = await tts.analyse(self.take(tmp_path / "b.wav", 0.12))
        assert quiet.snr > loud.snr + 15

    def test_every_preset_is_a_complete_chain(self):
        for name, chain in tts.PRESETS.items():
            for step in ("highpass", "afftdn", "acompressor", "alimiter", "loudnorm"):
                assert step in chain, (name, step)

    def test_the_noisy_preset_cuts_harder_than_the_quiet_one(self):
        """The trade is deliberate: an intelligible thin voice beats a warm one
        nobody can follow."""
        assert "highpass=f=110" in tts.PRESETS["shovqin"]
        assert "highpass=f=70" in tts.PRESETS["tinch"]
        assert "nf=-12" in tts.PRESETS["shovqin"]     # aggressive
        assert "nf=-45" in tts.PRESETS["tinch"]       # barely on

    def test_the_default_is_the_ordinary_room(self):
        assert tts.PRESETS["xona"] == tts.VOICE_CHAIN

    async def test_an_unreadable_file_does_not_pick_a_wrong_preset(self, tmp_path):
        """A failed measurement must not silently choose the harshest chain."""
        reading = await tts.analyse(tmp_path / "nothing.wav")
        assert reading.snr == 0.0
