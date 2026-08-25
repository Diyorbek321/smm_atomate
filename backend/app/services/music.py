"""Procedural music bed — a tempo-locked loop synthesised from scratch.

A promo with sound effects but no music feels naked, and waiting for licensed
tracks blocks every clip. This module writes its own bed: kick, hat, bass and
pad over a four-bar minor progression. Because the tempo is ours, scene cuts
can be snapped to the beat — which is the single biggest reason an edit reads
as professional.

The bed used to be one loop played at constant density from the first frame to
the last. Measured, that came out at 1.3 LU of loudness range — the number a
listener hears as "library music playing behind something". Three things fixed
it and are what the rest of this module is about:

* an **arrangement** (:func:`_arrangement`) — the bed enters on pads, picks up
  the rhythm section, and lifts into the final third, so there is somewhere for
  twenty seconds to go;
* **stereo** — pads are detuned and Haas-delayed per side, hats alternate
  across the field, kick and bass stay centred. Mono is the other half of why
  synthesised beds sound small;
* **sidechain ducking** (:func:`_duck`) — the harmony dips under every kick.
  It is the cheapest trick in modern production and the one most responsible
  for a bed sounding produced rather than assembled.
"""

from __future__ import annotations

import array
import math
import random
import struct
import wave
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 44100

#: Everything is written as semitones from A2, not as frequencies, so a
#: progression can be transposed for a brand without re-typing it.
A2 = 110.00


def hz(semitones: float) -> float:
    return A2 * (2 ** (semitones / 12))


#: Four-bar progressions, one per mood: (root, pad voicing) in semitones.
#:
#: There used to be exactly one of these, module-level, which meant every clip
#: this system had ever produced played the same four chords. Mood is the
#: single biggest lever on whether two videos sound like different pieces.
MOODS: dict[str, tuple[tuple[int, tuple[int, ...]], ...]] = {
    # i - VI - III - VII in A minor. Reflective; the original bed.
    "calm": ((0, (12, 15, 19)), (-4, (8, 12, 15)), (3, (10, 15, 19)), (-2, (10, 14, 17))),
    # I - V - vi - IV. The progression that reads as "this went well".
    "hopeful": ((3, (15, 19, 22)), (-2, (10, 14, 17)), (0, (12, 15, 19)), (-4, (8, 12, 15))),
    # i - bII - i - V. The flat second is what makes a countdown feel like one.
    "tense": ((0, (12, 15, 19)), (1, (13, 17, 20)), (0, (12, 15, 19)), (7, (19, 23, 26))),
    # IV - I - ii - vi, voiced wide. Slow, unhurried; for brand pieces.
    "warm": ((-4, (12, 15, 20)), (3, (15, 19, 22)), (5, (17, 20, 24)), (0, (12, 15, 19))),
}

#: Kept for callers that predate moods.
PROGRESSION = MOODS["calm"]

#: Sections, in the order a bar can belong to one.
INTRO, GROOVE, BUILD, LIFT = "intro", "groove", "build", "lift"

#: Per-section element gains: (pad, bass, kick, hat). A zero means the element
#: is silent for that bar, which is what actually creates the range — riding a
#: master fader over a constant loop only makes the same thing quieter.
#:
#: BUILD is the bar the kick drops out of. Measured per bar, an intro plus a
#: uniformly loud body still came out at 2.6 LU: the ear needs the floor taken
#: away before a lift reads as arrival rather than as "slightly louder".
SECTION_MIX: dict[str, tuple[float, float, float, float]] = {
    INTRO: (0.85, 0.00, 0.00, 0.30),
    GROOVE: (0.75, 1.00, 1.00, 0.90),
    BUILD: (0.95, 0.55, 0.00, 1.40),
    LIFT: (1.00, 1.00, 1.00, 1.30),
}

#: How far the harmony dips under a kick, and how long it takes to come back.
#: 0.55 is audible as movement without sounding like a pumping dance track.
DUCK_DEPTH = 0.55
DUCK_RELEASE = 0.26

#: Pad detune per side, in cents-ish multipliers, plus the Haas delay that
#: turns two nearly-identical signals into width. Past ~25 ms it stops being
#: width and starts being an echo.
PAD_SPREAD = 0.0022
HAAS_SECONDS = 0.013


@dataclass(slots=True)
class MusicSpec:
    seconds: float
    bpm: int = 96
    energy: str = "calm"            # calm | drive — kick density and hat rate
    seed: int = 7
    #: Which four-bar progression to play. See :data:`MOODS`.
    mood: str = "calm"
    #: Transpose the whole bed, in semitones. Derived per business so a brand's
    #: clips share a pitch centre the way they share a colour.
    key_shift: int = 0
    #: Which bar the loop opens on. Two clips in the same mood should not start
    #: on the same chord.
    rotation: int = 0


@dataclass(slots=True)
class Bed:
    """A rendered stereo bed.

    Iterating or slicing yields the mono downmix, so the callers that only ever
    wanted one channel — the montage clip, the video editor's music track —
    keep working unchanged while the promo path takes ``left``/``right``.
    """

    left: array.array
    right: array.array

    def __len__(self) -> int:
        return len(self.left)

    def __iter__(self) -> Iterator[float]:
        for left, right in zip(self.left, self.right, strict=False):
            yield (left + right) * 0.5

    def __getitem__(self, index: int | slice) -> float | list[float]:
        if isinstance(index, slice):
            return [
                (left + right) * 0.5
                for left, right in zip(self.left[index], self.right[index], strict=False)
            ]
        return (self.left[index] + self.right[index]) * 0.5

    def peak(self) -> float:
        return max(
            max((abs(v) for v in self.left), default=0.0),
            max((abs(v) for v in self.right), default=0.0),
        )


def channels_of(bed: Bed | Sequence[float] | None) -> tuple[Sequence[float], Sequence[float]] | None:
    """Split anything bed-shaped into two channels, duplicating a mono one."""
    if bed is None:
        return None
    if isinstance(bed, Bed):
        return bed.left, bed.right
    return bed, bed


def _envelope(index: int, total: int, attack: float, release: float) -> float:
    if total <= 0:
        return 0.0
    position = index / total
    if position < attack:
        return position / attack
    if position > 1 - release:
        return max(0.0, (1 - position) / release)
    return 1.0


def _kick(duration: float = 0.34) -> array.array:
    n = int(duration * SAMPLE_RATE)
    out = array.array("d", bytes(8 * n))
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 120 * math.exp(-24 * t) + 46
        body = math.sin(2 * math.pi * freq * t) * math.exp(-7 * t)
        # A phone speaker reproduces almost nothing at 46 Hz, so the kick was
        # inaudible on the device most of this is watched on. The click carries
        # the beat up where the speaker can actually play it.
        click = math.sin(2 * math.pi * 1800 * t) * math.exp(-260 * t) * 0.18
        out[i] = body + click
    return out


def _hat(duration: float = 0.06, seed: int = 3) -> array.array:
    """Band-limited shaker rather than a white-noise burst.

    This was raw ``uniform(-1, 1)`` — measurably white — and it played on
    every off-beat, which made it the single harshest element in the bed.
    """
    rng = random.Random(seed)
    n = int(duration * SAMPLE_RATE)
    out = array.array("d", bytes(8 * n))
    a_hi = 1.0 - math.exp(-2 * math.pi * 3800 / SAMPLE_RATE)
    a_lo = 1.0 - math.exp(-2 * math.pi * 1300 / SAMPLE_RATE)
    hi1 = hi2 = lo1 = lo2 = 0.0
    for i in range(n):
        white = rng.uniform(-1, 1)
        hi1 += (white - hi1) * a_hi                  # cascaded pair per side:
        hi2 += (hi1 - hi2) * a_hi                    # a single pole leaves the
        lo1 += (white - lo1) * a_lo                  # burst measurably white.
        lo2 += (lo1 - lo2) * a_lo
        out[i] = (hi2 - lo2) * math.exp(-60 * i / SAMPLE_RATE) * 1.35
    return out


def _bass(freq: float, duration: float) -> array.array:
    n = int(duration * SAMPLE_RATE)
    out = array.array("d", bytes(8 * n))
    for i in range(n):
        t = i / SAMPLE_RATE
        # Sine plus a touch of its octave keeps the note audible on phone speakers.
        tone = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
        # Soft saturation adds the upper harmonics a pure sine has none of;
        # without them the bass disappears entirely on a laptop speaker.
        out[i] = math.tanh(tone * 1.35) * _envelope(i, n, 0.02, 0.45) * 0.48
    return out


def _pad(freqs: tuple[float, ...], duration: float, spread: float = 0.0) -> array.array:
    """One side of the pad. `spread` detunes it away from the other side."""
    n = int(duration * SAMPLE_RATE)
    out = array.array("d", bytes(8 * n))
    for i in range(n):
        t = i / SAMPLE_RATE
        value = 0.0
        for index, freq in enumerate(freqs):
            detune = 1.0 + (index - 1) * 0.0015 + spread
            value += math.sin(2 * math.pi * freq * detune * t)
        out[i] = value / len(freqs) * _envelope(i, n, 0.18, 0.30) * 0.30
    return out


def pan_gain(pan: float) -> float:
    """Constant-power gain for one side. `pan` is +1 towards that side.

    Linear panning drops ~3 dB in the middle of a sweep, which on alternating
    hats is heard as the off-beat being quieter rather than as movement.
    """
    return math.sqrt(max(0.0, min(1.0, (1.0 + pan) / 2)))


def _place(target: array.array, source: Sequence[float], at_seconds: float, gain: float) -> None:
    if gain <= 0:
        return
    start = int(at_seconds * SAMPLE_RATE)
    total = len(target)
    for offset, sample in enumerate(source):
        index = start + offset
        if index >= total:
            break
        target[index] += sample * gain


def _arrangement(bars: int) -> list[str]:
    """Which section each bar belongs to.

    Short clips cannot afford an intro — a two-bar bed that spends its first
    bar on pads has no groove left — so they simply play the groove.
    """
    if bars <= 2:
        return [GROOVE] * bars
    if bars <= 4:
        return [INTRO] + [GROOVE] * (bars - 2) + [LIFT]
    if bars == 5:
        return [INTRO, GROOVE, GROOVE, BUILD, LIFT]
    lift = max(1, round(bars * 0.30))
    groove = bars - 2 - lift                       # one bar each for intro and build
    return [INTRO] + [GROOVE] * groove + [BUILD] + [LIFT] * lift


def _duck(channel: array.array, kicks: Sequence[float]) -> None:
    """Dip the harmony under every kick, in place.

    Written as one gain curve rather than per-kick multiplication so two kicks
    close together cannot duck the same samples twice and punch a hole in the
    bed.
    """
    if not kicks:
        return
    total = len(channel)
    release = int(DUCK_RELEASE * SAMPLE_RATE)
    if release <= 0:
        return
    gain = array.array("d", bytes(8 * total))
    for index in range(total):
        gain[index] = 1.0
    for at in kicks:
        start = int(at * SAMPLE_RATE)
        for offset in range(release):
            index = start + offset
            if index >= total:
                break
            # Exponential recovery: fast off the transient, slow back to unity.
            recovered = 1.0 - DUCK_DEPTH * math.exp(-4.0 * offset / release)
            if recovered < gain[index]:
                gain[index] = recovered
    for index in range(total):
        channel[index] *= gain[index]


def render_bed(spec: MusicSpec) -> Bed:
    """Synthesise the arranged stereo bed for `spec.seconds`."""
    beat = 60.0 / max(40, spec.bpm)
    bar = beat * 4
    total_samples = int((spec.seconds + 0.4) * SAMPLE_RATE)

    # Harmony and rhythm are kept apart until the very end so the kick can duck
    # the harmony without ducking itself.
    harmony_l = array.array("d", bytes(8 * total_samples))
    harmony_r = array.array("d", bytes(8 * total_samples))
    drums_l = array.array("d", bytes(8 * total_samples))
    drums_r = array.array("d", bytes(8 * total_samples))

    kick, hat = _kick(), _hat(seed=spec.seed)
    drive = spec.energy == "drive"
    pads: dict[tuple[int, int], array.array] = {}
    basses: dict[float, array.array] = {}

    progression = MOODS.get(spec.mood, MOODS["calm"])
    shift = spec.key_shift
    bars = max(1, math.ceil(spec.seconds / bar))
    sections = _arrangement(bars)
    kick_times: list[float] = []

    for bar_index in range(bars):
        section = sections[bar_index]
        pad_gain, bass_gain, kick_gain, hat_gain = SECTION_MIX[section]
        slot = (bar_index + spec.rotation) % len(progression)
        degree, voicing = progression[slot]
        root = hz(degree + shift)
        chord = tuple(hz(note + shift) for note in voicing)
        bar_start = bar_index * bar

        for side, (buffer, spread, delay) in enumerate((
            (harmony_l, -PAD_SPREAD, 0.0),
            (harmony_r, PAD_SPREAD, HAAS_SECONDS),
        )):
            key = (slot, side)
            if key not in pads:
                pads[key] = _pad(chord, bar, spread)
            _place(buffer, pads[key], bar_start + delay, 0.9 * pad_gain)

        if bass_gain:
            if root not in basses:
                basses[root] = _bass(root, beat * 1.7)
            for beat_index in (0, 2):
                at = bar_start + beat_index * beat
                _place(harmony_l, basses[root], at, 0.85 * bass_gain)
                _place(harmony_r, basses[root], at, 0.85 * bass_gain)

        if kick_gain:
            kick_beats = (0, 1, 2, 3) if drive else (0, 2)
            if section == LIFT and not drive:
                kick_beats = (0, 2, 3)          # the extra hit is the lift
            for beat_index in kick_beats:
                at = bar_start + beat_index * beat
                _place(drums_l, kick, at, kick_gain)
                _place(drums_r, kick, at, kick_gain)
                kick_times.append(at)

        if hat_gain:
            steps = 16 if (drive or section == LIFT) else 8
            for step in range(steps):
                at = bar_start + step * (bar / steps)
                accent = 1.0 if step % max(1, steps // 4) == 0 else 0.55
                # Alternating sides turn a metronome into movement.
                pan = -0.35 if step % 2 else 0.35
                level = 0.35 * accent * hat_gain
                _place(drums_l, hat, at, level * pan_gain(-pan))
                _place(drums_r, hat, at, level * pan_gain(pan))

    _duck(harmony_l, kick_times)
    _duck(harmony_r, kick_times)

    left = array.array("d", bytes(8 * total_samples))
    right = array.array("d", bytes(8 * total_samples))
    for index in range(total_samples):
        left[index] = harmony_l[index] + drums_l[index]
        right[index] = harmony_r[index] + drums_r[index]

    # Fade the last second so the bed never stops mid-note.
    fade_samples = int(min(1.2, spec.seconds * 0.2) * SAMPLE_RATE)
    end = int(spec.seconds * SAMPLE_RATE)
    for offset in range(fade_samples):
        index = end - fade_samples + offset
        if 0 <= index < total_samples:
            ramp = 1 - offset / fade_samples
            left[index] *= ramp
            right[index] *= ramp
    for index in range(end, total_samples):
        left[index] = 0.0
        right[index] = 0.0

    peak = max(
        max((abs(value) for value in left), default=0.0),
        max((abs(value) for value in right), default=0.0),
    )
    if peak > 0:
        scale = 0.62 / peak                      # a bed, not the main event
        for index in range(total_samples):
            left[index] *= scale
            right[index] *= scale
    return Bed(left, right)


def write_wav(
    samples: Bed | Sequence[float], path: Path, *, ceiling: float = 0.89
) -> Path:
    """Write float samples as 16-bit PCM, scaled so nothing clips.

    Everything this system synthesises — the bed here, the cue mix in
    kinetic.py — ends up as one WAV handed to ffmpeg as a single input, which
    is far cheaper than asking ffmpeg to mix twenty sources itself. A
    :class:`Bed` is written as stereo; anything else stays mono.
    """
    if isinstance(samples, Bed):
        channels: tuple[Sequence[float], ...] = (samples.left, samples.right)
    else:
        channels = (samples,)

    peak = max(
        (max((abs(value) for value in channel), default=0.0) for channel in channels),
        default=0.0,
    )
    scale = (ceiling / peak) if peak > ceiling else 1.0
    path.parent.mkdir(parents=True, exist_ok=True)

    frames = bytearray()
    if len(channels) == 1:
        for value in channels[0]:
            frames += struct.pack("<h", int(max(-1.0, min(1.0, value * scale)) * 32000))
    else:
        for left, right in zip(channels[0], channels[1], strict=False):
            frames += struct.pack(
                "<hh",
                int(max(-1.0, min(1.0, left * scale)) * 32000),
                int(max(-1.0, min(1.0, right * scale)) * 32000),
            )

    with wave.open(str(path), "wb") as out:
        out.setnchannels(len(channels))
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(bytes(frames))
    return path


def snap_to_beat(seconds: float, bpm: int, *, minimum_beats: int = 2) -> float:
    """Round a duration up to a whole number of beats so cuts land on the pulse."""
    beat = 60.0 / max(40, bpm)
    beats = max(minimum_beats, math.ceil(seconds / beat - 0.02))
    return round(beats * beat, 3)
