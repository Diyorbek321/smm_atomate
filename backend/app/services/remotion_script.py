"""Turns model copy into a Remotion render script — timing, order, sound cues.

Same division of labour as :mod:`app.services.promo_families`: the model writes
short strings, this module decides everything else. The Remotion side
(``backend/remotion``) owns layout and motion; this side owns *when*.

Every scene length is a whole number of bars, so each cut lands on a downbeat
of the tempo-locked bed, and every in-scene beat the renderer animates on is
the same beat the music plays. The cue list is derived from the same numbers,
which is why the SFX cannot drift from the picture.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.promo_families import Brand

COMPOSITION = "BrandPromo"
FPS = 30
WIDTH, HEIGHT = 1080, 1920
BPM = 120
BEATS_PER_BAR = 4

ICONS = ("bolt", "wallet", "shield", "star", "clock", "heart", "check", "pin", "users", "book")
PATTERNS = ("stripes", "checker", "dots")
MAX_FEATURES = 3

#: Minimum beats each scene needs for its own animation to finish (see the
#: matching scene in backend/remotion/src/scenes). Rounded up to whole bars.
_LOGO_BEATS = 8
_FEATURE_BEATS = 12
_STAT_BEATS = 8
_CTA_BEATS = 20
_PUNCH_BEATS = 5


@dataclass(frozen=True, slots=True)
class FeatureCopy:
    label: str
    title: str
    accent: str
    subtitle: str
    icon: str = "star"


@dataclass(frozen=True, slots=True)
class PromoCopy:
    """Everything the model writes. Empty optional parts drop their scene."""

    hook: list[str]
    punch: str
    tagline: str
    features: list[FeatureCopy]
    cta_tagline: str
    button: str
    lead: str = ""
    cta_accent: str = ""
    list_title: str = ""
    list_accent: str = ""
    items: list[str] = field(default_factory=list)
    stat_value: int = 0
    stat_suffix: str = ""
    stat_label: str = ""


def bars(beats: int) -> int:
    """Beats rounded up to whole bars, so the next cut sits on a downbeat."""
    return math.ceil(beats / BEATS_PER_BAR) * BEATS_PER_BAR


def pattern_for(name: str, category: str = "") -> str:
    """The logo band. Taxis get the checker every passenger already reads as 'taxi'."""
    text = f"{name} {category}".lower()
    if re.search(r"taks|taxi|такси", text):
        return "checker"
    return "dots" if category in ("beauty", "healthcare") else "stripes"


def _accent_in(title: str, accent: str) -> str:
    """Keep the accent only when it is really a word of the title."""
    words = {w.strip(".,!?—-").lower() for w in title.split()}
    return accent if accent and all(w.lower() in words for w in accent.split()) else ""


def _scene_list(copy: PromoCopy, brand: Brand, name: str, contact: str,
                pattern: str) -> list[tuple[int, dict[str, Any]]]:
    """(beats, scene) in clip order, before any timing is assigned."""
    hook_lines = [line for line in copy.hook if line.strip()][:3]
    hook_beats = bars(1 + 2 * len(hook_lines) + _PUNCH_BEATS)
    scenes: list[tuple[int, dict[str, Any]]] = [
        (hook_beats, {"type": "hook", "lines": hook_lines, "lead": copy.lead, "punch": copy.punch}),
        (bars(_LOGO_BEATS), {"type": "logo", "name": name, "tagline": copy.tagline, "pattern": pattern}),
    ]
    for index, feature in enumerate(copy.features[:MAX_FEATURES], start=1):
        scenes.append((bars(_FEATURE_BEATS), {
            "type": "feature", "index": f"{index:02d}", "label": feature.label,
            "title": feature.title, "accent": _accent_in(feature.title, feature.accent),
            "subtitle": feature.subtitle,
            "icon": feature.icon if feature.icon in ICONS else "star",
        }))
    items = [item for item in copy.items if item.strip()][:4]
    if copy.list_title.strip() and items:
        scenes.append((bars(2 + len(items) + 4), {
            "type": "list", "title": copy.list_title,
            "accent": _accent_in(copy.list_title, copy.list_accent), "items": items,
        }))
    if copy.stat_value > 0 and copy.stat_label.strip():
        scenes.append((bars(_STAT_BEATS), {
            "type": "stat", "value": copy.stat_value, "suffix": copy.stat_suffix[:3],
            "label": copy.stat_label,
        }))
    scenes.append((bars(_CTA_BEATS), {
        "type": "cta", "name": name, "tagline": copy.cta_tagline,
        "accent": _accent_in(copy.cta_tagline, copy.cta_accent),
        "button": copy.button or brand.cta, "contact": contact,
    }))
    return scenes


def _cues(scenes: list[dict[str, Any]], beat: float) -> list[tuple[str, float, float]]:
    """Sound cues for :func:`app.services.kinetic.mix_soundtrack`, from the same timing."""
    cues: list[tuple[str, float, float]] = []
    for scene in scenes:
        start = scene["at"][0]
        kind = scene["type"]
        if start > 0:
            cues.append(("whoosh", max(0.0, start - 0.12), 0.9))
        if kind in ("logo", "cta"):
            cues.append(("riser", max(0.0, start - 1.0), 0.6))
            cues.append(("impact", start + 0.04, 0.85))
        elif kind == "hook":
            for i in range(len(scene["lines"])):
                cues.append(("pop", start + beat * (1 + 2 * i), 0.6))
            cues.append(("impact", start + beat * (1 + 2 * len(scene["lines"])), 0.7))
        elif kind == "feature":
            cues.append(("tick", start + beat, 0.6))
        elif kind == "list":
            for i in range(len(scene["items"])):
                cues.append(("pop", start + beat * (2 + i), 0.65))
        elif kind == "stat":
            cues.append(("impact", start + beat * 4, 0.7))
        if kind == "cta":
            cues.append(("pop", start + beat * 4, 0.7))
    return sorted(cues, key=lambda cue: cue[1])


def build_script(
    copy: PromoCopy,
    brand: Brand,
    *,
    name: str,
    contact: str = "",
    pattern: str = "stripes",
    bpm: int = BPM,
    mood: str = "hopeful",
    energy: str = "drive",
) -> dict[str, Any]:
    """The full render script: Remotion props plus the music spec and cues."""
    if not copy.hook or not copy.punch.strip():
        raise ValueError("hook and punch are required")
    if (FPS * 60 * BEATS_PER_BAR) % bpm:
        # Scenes are whole bars; a bar that is not a whole number of frames
        # makes the renderer's rounded length disagree with the mux's `-t`.
        raise ValueError(f"bpm {bpm} does not give whole-frame bars at {FPS} fps")
    beat = 60.0 / bpm
    cursor = 0
    scenes: list[dict[str, Any]] = []
    for beats, scene in _scene_list(copy, brand, name, contact,
                                    pattern if pattern in PATTERNS else "stripes"):
        scenes.append({**scene, "at": [round(cursor * beat, 3), round((cursor + beats) * beat, 3)]})
        cursor += beats
    duration = round(cursor * beat, 3)

    return {
        "composition": COMPOSITION,
        "props": {
            "fps": FPS, "width": WIDTH, "height": HEIGHT, "duration": duration,
            "beat": round(beat, 4), "palette": dict(brand.palette), "scenes": scenes,
        },
        "music": {"bpm": bpm, "mood": mood, "energy": energy, "key_shift": brand.key_shift},
        "cues": _cues(scenes, beat),
        "duration": duration,
    }
