"""Procedural music bed — a tempo-locked loop synthesised from scratch.

A promo with sound effects but no music feels naked, and waiting for licensed
tracks blocks every clip. This module writes its own bed: kick, hat, bass and
pad over a four-bar minor progression. Because the tempo is ours, scene cuts
can be snapped to the beat — which is the single biggest reason an edit reads
as professional.
"""

from __future__ import annotations

import array
import math
import random
import struct
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 44100

#: Four bars in A minor: i - VI - III - VII. Roots in Hz, then the pad voicing.
PROGRESSION: tuple[tuple[float, tuple[float, ...]], ...] = (
    (110.00, (220.00, 261.63, 329.63)),      # Am
    (87.31, (174.61, 220.00, 261.63)),       # F
    (130.81, (196.00, 261.63, 329.63)),      # C
    (98.00, (196.00, 246.94, 293.66)),       # G
)


@dataclass(slots=True)
class MusicSpec:
    seconds: float
    bpm: int = 96
    energy: str = "calm"            # calm | drive
    seed: int = 7


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
        out[i] = math.sin(2 * math.pi * freq * t) * math.exp(-7 * t)
    return out


def _hat(duration: float = 0.05, seed: int = 3) -> array.array:
    rng = random.Random(seed)
    n = int(duration * SAMPLE_RATE)
    out = array.array("d", bytes(8 * n))
    for i in range(n):
        out[i] = rng.uniform(-1, 1) * math.exp(-70 * i / SAMPLE_RATE) * 0.5
    return out


def _bass(freq: float, duration: float) -> array.array:
    n = int(duration * SAMPLE_RATE)
    out = array.array("d", bytes(8 * n))
    for i in range(n):
        t = i / SAMPLE_RATE
        # Sine plus a touch of its octave keeps the note audible on phone speakers.
        tone = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
        out[i] = tone * _envelope(i, n, 0.02, 0.45) * 0.55
    return out


def _pad(freqs: tuple[float, ...], duration: float) -> array.array:
    n = int(duration * SAMPLE_RATE)
    out = array.array("d", bytes(8 * n))
    for i in range(n):
        t = i / SAMPLE_RATE
        value = 0.0
        for index, freq in enumerate(freqs):
            detune = 1.0 + (index - 1) * 0.0015      # slight spread, not a chorus
            value += math.sin(2 * math.pi * freq * detune * t)
        out[i] = value / len(freqs) * _envelope(i, n, 0.18, 0.30) * 0.30
    return out


def _place(target: array.array, source: array.array, at_seconds: float, gain: float) -> None:
    start = int(at_seconds * SAMPLE_RATE)
    total = len(target)
    for offset, sample in enumerate(source):
        index = start + offset
        if index >= total:
            break
        target[index] += sample * gain


def render_bed(spec: MusicSpec) -> array.array:
    """Synthesise the loop for `spec.seconds`, ending on a fade-out."""
    beat = 60.0 / max(40, spec.bpm)
    bar = beat * 4
    total_samples = int((spec.seconds + 0.4) * SAMPLE_RATE)
    track = array.array("d", bytes(8 * total_samples))

    kick, hat = _kick(), _hat(seed=spec.seed)
    drive = spec.energy == "drive"
    pads: dict[int, array.array] = {}
    basses: dict[float, array.array] = {}

    bar_index = 0
    while bar_index * bar < spec.seconds:
        root, chord = PROGRESSION[bar_index % len(PROGRESSION)]
        bar_start = bar_index * bar

        if bar_index not in pads:
            pads[bar_index % len(PROGRESSION)] = pads.get(
                bar_index % len(PROGRESSION), _pad(chord, bar)
            )
        _place(track, pads[bar_index % len(PROGRESSION)], bar_start, 0.9)

        if root not in basses:
            basses[root] = _bass(root, beat * 1.7)
        for beat_index in (0, 2):
            _place(track, basses[root], bar_start + beat_index * beat, 0.85)

        kick_beats = (0, 1, 2, 3) if drive else (0, 2)
        for beat_index in kick_beats:
            _place(track, kick, bar_start + beat_index * beat, 1.0)

        steps = 16 if drive else 8
        for step in range(steps):
            at = bar_start + step * (bar / steps)
            accent = 1.0 if step % (steps // 4) == 0 else 0.55
            _place(track, hat, at, 0.35 * accent)

        bar_index += 1

    # Fade the last second so the bed never stops mid-note.
    fade_samples = int(min(1.2, spec.seconds * 0.2) * SAMPLE_RATE)
    end = int(spec.seconds * SAMPLE_RATE)
    for offset in range(fade_samples):
        index = end - fade_samples + offset
        if 0 <= index < total_samples:
            track[index] *= 1 - offset / fade_samples
    for index in range(end, total_samples):
        track[index] = 0.0

    peak = max((abs(value) for value in track), default=0.0)
    if peak > 0:
        scale = 0.62 / peak                      # a bed, not the main event
        for index in range(total_samples):
            track[index] *= scale
    return track


def write_wav(samples: Sequence[float], path: Path, *, ceiling: float = 0.89) -> Path:
    """Write float samples as 16-bit mono PCM, scaled so nothing clips.

    Everything this system synthesises — the bed here, the cue mix in
    kinetic.py — ends up as one WAV handed to ffmpeg as a single input, which
    is far cheaper than asking ffmpeg to mix twenty sources itself.
    """
    peak = max((abs(value) for value in samples), default=0.0)
    scale = (ceiling / peak) if peak > ceiling else 1.0
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for value in samples:
        frames += struct.pack("<h", int(max(-1.0, min(1.0, value * scale)) * 32000))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(bytes(frames))
    return path


def snap_to_beat(seconds: float, bpm: int, *, minimum_beats: int = 2) -> float:
    """Round a duration up to a whole number of beats so cuts land on the pulse."""
    beat = 60.0 / max(40, bpm)
    beats = max(minimum_beats, math.ceil(seconds / beat - 0.02))
    return round(beats * beat, 3)
