"""Uzbek narration for a clip, and the timing the edit is cut against.

Clips shipped mute. The agent wrote a `say` line for every scene, the composer
estimated each scene's length from that line's word count at :data:`WPM`, and
then nothing spoke it — so every clip was cut to the rhythm of speech nobody
could hear. This is the layer that was missing, ported from the lab's `vo.py`
where it was worked out against real listening.

Two things come back, and the second is the one the renderer actually needs:

* the audio, one WAV per sentence — synthesised whole rather than in fragments,
  because a sentence cut into pieces and rejoined loses its prosody and reads
  as a robot;
* :class:`Line` timings, including per-word positions, so scene lengths are
  *measured* instead of estimated and karaoke lines land on the syllable.

The synthesiser is one source of narration and deliberately not the only one.
:func:`measure` takes audio a person recorded and produces the same timings, so
an owner's own voice drives the edit exactly as a generated one does — the cuts
still land on their delivery, and the daily quota stops mattering. The one thing
that must *not* carry over is the tempo correction: a model reads at whatever
pace it likes and is stretched to :data:`TARGET_WPM`, but a person's pace is the
performance, and speeding it up to hit a number would be editing the wrong end
of the problem.

**Quota is a first-class outcome, not an error.** The free tier allows ten
requests per model per day and one clip spends one per scene, so running out
mid-clip is the normal case rather than the exceptional one. Running out
returns the lines that did synthesise; the composer already treats a missing
timing as a silent scene and estimates it, so a clip half-voiced still renders.
Failing the render instead would turn a partial success into nothing at all.
"""

from __future__ import annotations

import array
import asyncio
import base64
import contextlib
import random
import re
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.translit import convert

log = get_logger(__name__)

#: Quota is counted per model, so a list is a budget rather than a preference:
#: when the first is spent for the day the next one still has its own ten.
MODELS: tuple[str, ...] = (
    "gemini-2.5-flash-preview-tts",
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-pro-preview-tts",
)

VOICE = "Orus"

#: Delivery rate the narration is written against; must match
#: :data:`app.services.promo_scenes.WPM` or a voiced scene and an estimated one
#: in the same clip run at different speeds.
TARGET_WPM = 150

#: What the renderer mixes. Resampling speech is a quality loss for no reason
#: when ffmpeg can hand it over at the mix rate directly.
MIX_RATE = 44100

STYLE = (
    "Read this text FAST and punchy as TURKISH, like a high-energy Reels "
    "voiceover by a male business coach. Apply Turkish pronunciation rules "
    "strictly. Urgent, confident, no pauses. Text:\n\n"
)

#: What a dialogue engineer does to a voice recorded on a phone, as one
#: ffmpeg chain. The order is the order, and each step is here because the one
#: before it created the problem it solves:
#:
#: * **highpass** — handling noise and room rumble live below speech and carry
#:   real energy; leaving them in makes the compressor duck for a sound nobody
#:   can hear.
#: * **afftdn** — spectral denoise before compression, never after. Compression
#:   raises the noise floor along with the voice, so a hiss that was inaudible
#:   becomes the loudest thing in a pause.
#: * **equalizer ×2** — a cut where a small room piles up, a lift where
#:   consonants live. Phone microphones are muddy in the first and shy in the
#:   second.
#: * **deesser** — after the presence lift, because that lift is what makes the
#:   sibilance sharp enough to need taming.
#: * **acompressor** — evens a delivery that leans in and drifts back.
#: * **alimiter** — catches what the make-up gain pushed past the ceiling.
#: * **loudnorm** — per line, so line three is not quieter than line one. The
#:   master pass in the renderer sets the final level; this one only makes the
#:   lines agree with each other, and sits below the master target to leave it
#:   room.

#: The chain, tuned three ways. Which one a take needs is not a judgement a
#: language model can make — it cannot hear, and the answer is in the numbers.
#: So it is measured, not asked: :func:`analyse` reads the signal-to-noise ratio
#: and :func:`preset_for` picks. The wrong preset is audible in both directions,
#: which is why this is chosen per take rather than fixed.
PRESETS: dict[str, str] = {
    # A treated room or a close mic. There is nothing to remove, and removing
    # it anyway costs detail — so denoise is barely on and the chain is mostly
    # levelling.
    "tinch": (
        "highpass=f=70,"
        "afftdn=nf=-45,"
        "equalizer=f=3500:t=q:w=1.4:g=1.5,"
        "deesser=i=0.3,"
        "acompressor=threshold=-20dB:ratio=2.5:attack=10:release=160:makeup=1.5,"
        "alimiter=limit=0.95,"
        "loudnorm=I=-18:TP=-2:LRA=7"
    ),
    # The common case: a phone, held, in an ordinary room.
    "xona": (
        "highpass=f=80,"
        "afftdn=nf=-25,"
        "equalizer=f=300:t=q:w=1.2:g=-2,"
        "equalizer=f=3500:t=q:w=1.4:g=2.5,"
        "deesser=i=0.4,"
        "acompressor=threshold=-18dB:ratio=3:attack=8:release=140:makeup=2,"
        "alimiter=limit=0.95,"
        "loudnorm=I=-18:TP=-2:LRA=7"
    ),
    # Traffic, a fan, a cafe. Denoise hard and high-pass higher, and accept
    # that the voice thins — an intelligible thin voice beats a warm one nobody
    # can follow.
    "shovqin": (
        "highpass=f=110,"
        "afftdn=nf=-12,"
        "anlmdn=s=0.0002,"
        "equalizer=f=250:t=q:w=1.2:g=-3,"
        "equalizer=f=3200:t=q:w=1.4:g=3,"
        "deesser=i=0.5,"
        "acompressor=threshold=-16dB:ratio=4:attack=6:release=120:makeup=3,"
        "alimiter=limit=0.94,"
        "loudnorm=I=-18:TP=-2:LRA=6"
    ),
}

#: Above this the recording is clean enough that denoising costs more than it
#: saves; below the lower one, the noise is part of the signal's neighbourhood.
#: The name the rest of the module uses for the ordinary case.
VOICE_CHAIN = PRESETS["xona"]

SNR_CLEAN = 26.0
SNR_NOISY = 13.0


@dataclass(slots=True)
class Reading:
    """What the numbers say about a take."""

    rms_peak_db: float = -99.0
    rms_trough_db: float = -99.0
    peak_db: float = -99.0
    flat: float = 0.0

    @property
    def snr(self) -> float:
        """Loudest speech against the quietest pause.

        `astats` reports a "Noise floor" and it is not this: it comes out
        *above* the overall RMS on ordinary material, because it measures
        minimum local peaks rather than the level between words. What a
        listener calls noise is what is left when nobody is talking, which is
        the trough — and the difference from the peak is what they hear as
        "clean" or "noisy".
        """
        return round(self.rms_peak_db - self.rms_trough_db, 2)

    @property
    def clipped(self) -> bool:
        # `Flat factor` counts consecutive identical samples: a waveform with
        # its top sliced off. Peak alone cannot tell a loud take from a clipped
        # one.
        return self.flat > 1.0 or self.peak_db > -0.5


async def analyse(path: Path) -> Reading:
    """Measure a take with ffmpeg's `astats`."""
    from app.services.video import ffmpeg_path

    binary = ffmpeg_path()
    if binary is None:
        return Reading()
    process = await asyncio.create_subprocess_exec(
        binary, "-hide_banner", "-i", str(path), "-af", "astats", "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    text = stderr.decode(errors="replace")

    def value(label: str, fallback: float) -> float:
        found = re.findall(rf"{label}:\s*(-?\d+\.?\d*)", text)
        try:
            return float(found[-1]) if found else fallback
        except ValueError:
            return fallback

    return Reading(
        rms_peak_db=value("RMS peak dB", -99.0),
        rms_trough_db=value("RMS trough dB", -99.0),
        peak_db=value("Peak level dB", -99.0),
        flat=value("Flat factor", 0.0),
    )


def preset_for(reading: Reading) -> str:
    """Which chain this take needs, from what was measured."""
    if reading.snr >= SNR_CLEAN:
        return "tinch"
    if reading.snr <= SNR_NOISY:
        return "shovqin"
    return "xona"


#: Trim leading and trailing silence. The model pads both ends unevenly, and
#: that padding lands inside the scene length — a half-second of nothing before
#: every line reads as hesitation across a whole clip.
TRIM = (
    "silenceremove=start_periods=1:start_silence=0.04:start_threshold=-45dB,"
    "areverse,"
    "silenceremove=start_periods=1:start_silence=0.04:start_threshold=-45dB,"
    "areverse"
)

VOWELS = frozenset("aeiouAEIOUıİöÖüÜ")

#: atempo beyond this stops sounding like a person talking faster.
TEMPO_FLOOR, TEMPO_CEIL = 0.5, 2.0


class QuotaExhausted(Exception):
    """Every model's daily allowance is spent. Not a failure — a stopping point."""


@dataclass(slots=True)
class Word:
    w: str
    at: float
    #: Bold in karaoke. The agent marks emphasis with *asterisks* in `say`.
    b: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"w": self.w, "at": self.at, "b": self.b}


@dataclass(slots=True)
class Line:
    src: str
    dur: float
    words: list[Word] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"src": self.src, "dur": self.dur,
                "words": [w.as_dict() for w in self.words]}


def available() -> bool:
    """Whether narration can be attempted at all."""
    return bool(get_settings().gemini_api_key)


def _weight(word: str) -> float:
    """Roughly how long this word takes to say.

    Word positions inside a sentence are interpolated rather than measured —
    the API returns no alignment — so the model has to be crude but not wrong.
    Vowels carry the length, consonants are brief. Error accumulates across a
    sentence, but a sentence is three seconds and karaoke tolerates that; it
    would not survive being applied across a whole clip.
    """
    vowels = sum(character in VOWELS for character in word)
    return 1.0 + 1.6 * vowels + 0.30 * (len(word) - vowels)


def _words_for(marked: str, duration: float) -> list[Word]:
    tokens = marked.split()
    if not tokens:
        return []
    weights = [_weight(token.strip("*.,!?—:;")) for token in tokens]
    total = sum(weights) or 1.0
    out, clock = [], 0.0
    for token, weight in zip(tokens, weights, strict=True):
        out.append(Word(w=token.replace("*", ""),
                        at=round(clock / total * duration, 3),
                        b=token.startswith("*") or token.endswith("*")))
        clock += weight
    return out


async def _ffmpeg(args: list[str]) -> None:
    from app.services.video import ffmpeg_path

    binary = ffmpeg_path()
    if binary is None:
        raise RuntimeError("ffmpeg is not installed — narration unavailable")
    process = await asyncio.create_subprocess_exec(
        binary, "-hide_banner", "-loglevel", "error", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg: {stderr[-300:].decode(errors='replace')}")


def duration_of(path: Path) -> float:
    with contextlib.closing(wave.open(str(path))) as handle:
        return handle.getnframes() / handle.getframerate()


def read_mono(path: Path) -> tuple[array.array, int]:
    """A WAV as floats in [-1, 1], plus its rate. Stereo is folded to mono."""
    with contextlib.closing(wave.open(str(path))) as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        raw = array.array("h")
        raw.frombytes(handle.readframes(handle.getnframes()))
    if channels > 1:
        folded = array.array("h", [0]) * (len(raw) // channels)
        for index in range(len(folded)):
            block = raw[index * channels:(index + 1) * channels]
            folded[index] = int(sum(block) / channels)
        raw = folded
    return array.array("d", (sample / 32768.0 for sample in raw)), rate


async def _synthesise(text: str, out: Path, model: str) -> None:
    """One sentence, one request. Raises on anything but a spent daily quota."""
    from app.core.exceptions import ProviderError
    from app.services.http import get_client

    settings = get_settings()
    body = {
        "contents": [{"parts": [{"text": STYLE + convert(text)}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}
            },
        },
    }
    client = await get_client("gemini-tts", timeout=240)
    response = await client.post(
        f"{settings.gemini_base_url}/models/{model}:generateContent",
        json=body,
        headers={"x-goog-api-key": settings.gemini_api_key,
                 "Content-Type": "application/json"},
    )
    if response.status_code in (429, 500, 503):
        raise _Retryable(response.status_code, response.text)
    if response.status_code >= 400:
        raise ProviderError("gemini-tts", f"{response.status_code}: {response.text[:200]}")

    part = response.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
    pcm = base64.b64decode(part["data"])
    match = re.search(r"rate=(\d+)", str(part.get("mimeType", "")))
    rate = int(match.group(1)) if match else 24000
    with contextlib.closing(wave.open(str(out), "wb")) as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)


class _Retryable(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"{status}")
        self.status = status
        self.daily = "PerDay" in body


async def _synthesise_with_fallback(text: str, out: Path) -> str:
    """Walk the model list until one speaks. Returns the model that did.

    A per-minute limit is worth waiting out; a daily one is not, and the two
    arrive as the same 429. Only the body distinguishes them, which is why the
    quota kind is read there rather than inferred from the status.
    """
    for model in MODELS:
        for attempt in range(3):
            try:
                await _synthesise(text, out, model)
                return model
            except _Retryable as exc:
                if exc.daily:
                    log.info("tts_daily_quota_spent", model=model)
                    break
                if attempt == 2:
                    break
                await asyncio.sleep(15 * (attempt + 1))
    raise QuotaExhausted()


async def narrate(says: list[str], out_dir: Path, *, name: str = "vo",
                  wpm: int = TARGET_WPM) -> list[Line]:
    """Speak each line, return timings for as many as the quota allowed.

    Stops at the first exhausted line rather than skipping it: the composer
    reads `timing` positionally, so a hole in the middle would shift every
    later scene onto the wrong line's audio. Stopping keeps the prefix correct.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # Seeded on the clip's name so a re-render sounds identical, while two
    # different clips get different jitter.
    rng = random.Random(name)
    lines: list[Line] = []

    for index, marked in enumerate(says):
        clean = marked.replace("*", "").strip()
        if not clean:
            break
        raw = out_dir / f"{name}-{index}-raw.wav"
        final = out_dir / f"{name}-{index}.wav"
        try:
            await _synthesise_with_fallback(clean, raw)
        except QuotaExhausted:
            log.warning("tts_quota_exhausted", spoken=len(lines), total=len(says))
            break

        await _ffmpeg(["-i", str(raw), "-af", TRIM, "-y", str(raw.with_suffix(".trim.wav"))])
        raw.with_suffix(".trim.wav").replace(raw)

        natural = duration_of(raw)
        target = max(0.4, len(clean.split()) / wpm * 60)
        tempo = natural / target
        # A clip where every sentence runs at exactly the same rate is a tell.
        tempo *= rng.uniform(0.96, 1.05)
        tempo = max(TEMPO_FLOOR, min(TEMPO_CEIL, tempo))
        await _ffmpeg(["-i", str(raw), "-af", f"atempo={tempo:.4f}",
                       "-ar", str(MIX_RATE), "-ac", "1", "-y", str(final)])
        raw.unlink(missing_ok=True)

        spoken = round(duration_of(final), 3)
        lines.append(Line(src=str(final), dur=spoken,
                          words=_words_for(marked, spoken)))
        log.info("tts_line", index=index, seconds=spoken,
                 wpm=round(len(clean.split()) / max(spoken, 0.1) * 60))

    return lines


def envelope(voice: list[tuple[Path, float]], total: int, rate: int = MIX_RATE,
             attack: float = 0.08, release: float = 0.35) -> array.array | None:
    """How hard to hold the music down, sample by sample.

    A bed mixed at speech level buries the speech; a bed dropped for the whole
    clip wastes the music. This follows the narration instead — fast to duck so
    a word is never clipped by the music, slow to recover so the bed does not
    pump between sentences.
    """
    if not voice:
        return None
    gate = array.array("d", bytes(8 * total))
    for path, at in voice:
        try:
            start = int(max(0.0, at) * rate)
            length = int(duration_of(path) * rate)
        except Exception:  # pragma: no cover - unreadable file is handled upstream
            continue
        for index in range(start, min(total, start + length)):
            gate[index] = 1.0

    attack_step = 1.0 / max(1, int(attack * rate))
    release_step = 1.0 / max(1, int(release * rate))
    level = 0.0
    for index in range(total):
        target = gate[index]
        level = (min(target, level + attack_step) if target > level
                 else max(target, level - release_step))
        gate[index] = level
    return gate


def as_timing(lines: list[Line]) -> list[dict[str, Any]]:
    """The shape :func:`app.services.promo_scenes.build_script` expects."""
    return [line.as_dict() for line in lines]


# --------------------------------------------------------------------------- #
# Narration somebody recorded themselves
# --------------------------------------------------------------------------- #

#: How much quieter than the peak counts as a pause between lines.
SPLIT_NOISE_DB = -34
#: A gap shorter than this is a breath inside a sentence, not a line break.
SPLIT_MIN_SILENCE = 0.45
#: Air kept on each side of a cut. Enough that a consonant is never clipped,
#: little enough that the pause itself does not travel into the scene.
SPLIT_PAD = 0.12


async def _silences(path: Path) -> list[tuple[float, float]]:
    """Where the speaker stopped, via ffmpeg's silencedetect."""
    from app.services.video import ffmpeg_path
    from app.services.video_editor import parse_silences

    binary = ffmpeg_path()
    if binary is None:
        raise RuntimeError("ffmpeg is not installed — narration unavailable")
    process = await asyncio.create_subprocess_exec(
        binary, "-hide_banner", "-i", str(path),
        "-af", f"silencedetect=noise={SPLIT_NOISE_DB}dB:d={SPLIT_MIN_SILENCE}",
        "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    return parse_silences(stderr.decode(errors="replace"))


async def _normalise(source: Path, target: Path,
                     start: float | None = None, end: float | None = None,
                     *, enhance: bool = False, preset: str = "") -> None:
    """One line, trimmed of its edges and handed over at the mix rate.

    No `atempo` here, unlike :func:`narrate`. A person's pace is the take; a
    synthesiser's is an artefact of the model.

    ``enhance`` runs :data:`VOICE_CHAIN`. It is off for synthesised speech and
    on for anything a person recorded — and that asymmetry is deliberate, not
    an oversight. A synthesiser hands over a clean, level, roomless signal;
    denoising it removes detail to fix a problem it does not have, and
    compressing it flattens prosody the model was asked for. A phone in a room
    has every one of those problems.
    """
    args = ["-i", str(source)]
    if start is not None:
        args = ["-ss", f"{start:.3f}", *args]
    if end is not None and start is not None:
        args += ["-t", f"{max(0.05, end - start):.3f}"]
    chain = f"{PRESETS.get(preset) or VOICE_CHAIN},{TRIM}" if enhance else TRIM
    args += ["-af", chain, "-ar", str(MIX_RATE), "-ac", "1", "-y", str(target)]
    try:
        await _ffmpeg(args)
    except RuntimeError as exc:
        if not enhance:
            raise
        # A build without one of these filters must not cost the clip its
        # narration; the untreated take is worse audio, not no audio.
        log.warning("voice_chain_unavailable", error=str(exc)[:200])
        args[args.index(chain)] = TRIM
        await _ffmpeg(args)


async def measure(paths: list[Path], says: list[str], out_dir: Path,
                  *, name: str = "own") -> list[Line]:
    """Turn recordings into the timings the composer cuts against.

    One file per narrated line, in order. Extra files are ignored and missing
    ones simply end the list — the composer already treats a line with no
    timing as a silent scene and estimates it, so a half-recorded clip renders
    rather than failing.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # One reading for the set: these are takes from one session, in one room,
    # on one microphone. Measuring each separately would let a short line with
    # no pause in it pick a preset for the whole recording.
    preset = ""
    if paths and Path(paths[0]).exists():
        preset = preset_for(await analyse(Path(paths[0])))
        log.info("voice_preset", preset=preset)

    lines: list[Line] = []
    for index, marked in enumerate(says):
        if index >= len(paths):
            break
        source = Path(paths[index])
        if not source.exists():
            log.warning("voice_missing", index=index, src=str(source))
            break
        final = out_dir / f"{name}-{index}.wav"
        await _normalise(source, final, enhance=True, preset=preset)
        spoken = round(duration_of(final), 3)
        lines.append(Line(src=str(final), dur=spoken,
                          words=_words_for(marked, spoken)))
        log.info("voice_measured", index=index, seconds=spoken)
    return lines


async def split(recording: Path, says: list[str], out_dir: Path,
                *, name: str = "own") -> list[Line]:
    """One take of the whole script, cut into lines at the longest pauses.

    Recording each line as its own file is tidy and nobody does it. People read
    the script once, top to bottom, pausing between lines — so the pauses are
    the line breaks, and the longest `len(says) - 1` of them are the ones that
    matter. Splitting at their midpoints keeps a little air on both sides.

    Raises when the take has fewer pauses than the script has lines: guessing a
    split point inside a sentence would cut somebody off mid-word, and the
    honest answer is to say the take does not match the script.
    """
    wanted = len(says)
    if wanted <= 1:
        return await measure([recording], says, out_dir, name=name)

    total = duration_of(recording) if recording.suffix == ".wav" else 0.0
    gaps = await _silences(recording)
    if total <= 0:
        # Not a WAV: ffmpeg knows the length even when `wave` does not.
        normalised = out_dir / f"{name}-full.wav"
        out_dir.mkdir(parents=True, exist_ok=True)
        await _normalise(recording, normalised, enhance=True)
        recording, total = normalised, duration_of(normalised)
        gaps = await _silences(recording)

    inner = [(start, end) for start, end in gaps if start > 0.15 and end < total - 0.15]
    if len(inner) < wanted - 1:
        raise ValueError(
            f"yozuvda {len(inner)} ta pauza bor, ssenariyda {wanted} ta gap — "
            "gaplar orasida aniqroq to'xtab qayta yozing"
        )

    # The longest pauses are the line breaks; the rest are breaths.
    chosen = sorted(sorted(inner, key=lambda g: g[1] - g[0], reverse=True)[:wanted - 1])
    spans: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in chosen:
        spans.append((cursor, min(total, start + SPLIT_PAD)))
        cursor = max(0.0, end - SPLIT_PAD)
    spans.append((cursor, total))

    out_dir.mkdir(parents=True, exist_ok=True)
    # Measured on the whole take, where the pauses that reveal the noise floor
    # actually are. A single line, cut out, may contain none.
    reading = await analyse(recording)
    preset = preset_for(reading)
    log.info("voice_preset", preset=preset, snr=reading.snr,
             clipped=reading.clipped)

    lines: list[Line] = []
    for index, marked in enumerate(says):
        final = out_dir / f"{name}-{index}.wav"
        await _normalise(recording, final, *spans[index], enhance=True, preset=preset)
        spoken = round(duration_of(final), 3)
        lines.append(Line(src=str(final), dur=spoken,
                          words=_words_for(marked, spoken)))
    log.info("voice_split", lines=len(lines), pauses=len(inner),
             seconds=round(total, 2))
    return lines
