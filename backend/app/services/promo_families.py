"""The promo families — authored layouts a model fills in, rather than designs.

Every function here returns a complete script for
:func:`app.services.promo.render_promo`. The geometry, the timing and the
motion are fixed in code; the caller supplies only copy.

That split is deliberate. Asking a language model for arbitrary scene geometry
gets arbitrary geometry — text that overflows, props behind headlines, cuts
that land off the beat. Asking it for five short lines gets five short lines.

Cuts land on the beat because the bed is tempo-locked; see
:func:`app.services.music.snap_to_beat`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: Default tempo for anything without its own profile.
BPM = 120
BEAT = 60.0 / BPM

#: What each family should sound like.
#:
#: The bed used to be one progression at one tempo for every clip, which is why
#: ten visually distinct families still sounded like one video. A countdown and
#: a brand piece are doing opposite rhetorical work; they should not share a
#: chord progression, and they certainly should not share a pulse.
PROFILES: dict[str, dict[str, Any]] = {
    "statement":  {"mood": "calm",    "bpm": 120, "energy": "calm"},
    "sanoq":      {"mood": "hopeful", "bpm": 122, "energy": "drive"},
    "taqqoslash": {"mood": "calm",    "bpm": 118, "energy": "calm"},
    "savol":      {"mood": "tense",   "bpm": 120, "energy": "drive"},
    "raqam":      {"mood": "hopeful", "bpm": 124, "energy": "drive"},
    "isbot":      {"mood": "warm",    "bpm": 112, "energy": "calm"},
    "ustoz":      {"mood": "warm",    "bpm": 108, "energy": "calm"},
    "uzluksiz":   {"mood": "warm",    "bpm": 100, "energy": "calm"},
    "dastur":     {"mood": "calm",    "bpm": 116, "energy": "calm"},
    "muddat":     {"mood": "tense",   "bpm": 128, "energy": "drive"},
}


def profile(family: str) -> dict[str, Any]:
    return PROFILES.get(family, {"mood": "calm", "bpm": BPM, "energy": "calm"})

#: Fallbacks used when a business has not set brand colours yet.
DEFAULT_PALETTE = {
    "bg": "#0B0F14", "ink": "#F2F6F8", "accent": "#2FD9C4",
    "brand": "#37B3A2", "muted": "#63727E",
}

FAMILIES = ("statement", "sanoq", "taqqoslash", "savol", "raqam", "isbot",
            "ustoz", "uzluksiz", "dastur", "muddat")


@dataclass(slots=True)
class Brand:
    """Everything a family needs that is not copy."""

    palette: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PALETTE))
    mark: str = ""
    props: list[str] = field(default_factory=list)
    cta: str = ""
    #: Semitones to transpose the bed. Derived from the mark, so every clip a
    #: business ships sits in the same key — a signature you hear rather than
    #: see, and one no two neighbouring businesses share.
    key_shift: int = 0

    @classmethod
    def from_colors(cls, colors: dict[str, Any] | None, *, mark: str = "",
                    props: list[str] | None = None, cta: str = "") -> Brand:
        palette = dict(DEFAULT_PALETTE)
        for key in ("bg", "ink", "accent", "brand", "muted"):
            value = (colors or {}).get(key) or (colors or {}).get(
                {"ink": "text"}.get(key, key))
            if isinstance(value, str) and value.startswith("#"):
                palette[key] = value
        shift = (sum(ord(c) for c in mark) % 7) - 3 if mark else 0
        return cls(palette=palette, mark=mark, props=list(props or []), cta=cta,
                   key_shift=shift)

    def prop(self, index: int) -> str | None:
        return self.props[index % len(self.props)] if self.props else None

    def glow(self) -> str:
        accent = self.palette["accent"].lstrip("#")
        r, g, b = (int(accent[i:i + 2], 16) for i in (0, 2, 4))
        return f"rgba({r},{g},{b},.14)"


def _shell(name: str, brand: Brand, duration: float, scenes: list[dict],
           *, align: str | None = None, mark_until: float | None = None,
           extra: dict[str, Any] | None = None) -> dict:
    script: dict[str, Any] = {
        "name": name, "family": name, "duration": round(duration, 3),
        "fps": 30, "size": [1080, 1920],
        "palette": brand.palette, "glow": brand.glow(),
        "music": _music(name, brand, scenes),
        "scenes": scenes,
    }
    if align:
        script["align"] = align
    if extra:
        script.update(extra)
    if brand.mark:
        script["mark"] = {"text": brand.mark, "from": 0.8}
        if mark_until is not None:
            script["mark"]["until"] = round(mark_until, 3)
    return script


def _music(family: str, brand: Brand, scenes: list[dict]) -> dict[str, Any]:
    """The bed this clip plays: family profile, brand key, content rotation."""
    spec = profile(family)
    # Rotation comes from the copy itself, so two clips in the same family open
    # on different chords without anyone having to pass a seed around.
    weight = sum(
        len(str(line.get("text", "")) + str(line.get("word", "")))
        for scene in scenes
        for pane in (scene.get("columns") or [scene])
        for line in pane.get("lines", [])
    )
    return {"bpm": spec["bpm"], "mood": spec["mood"], "energy": spec["energy"],
            "key_shift": brand.key_shift, "rotation": weight % 4}


def _cta(start: float, end: float, brand: Brand, headline: str) -> dict:
    return {"at": [round(start, 3), round(end, 3)], "align": "center", "transition": "whip",
            "lines": [
                {"kind": "display", "text": headline, "size": 150, "at": 0.02, "dy": 66, "out": 99},
                {"kind": "kicker", "text": brand.mark[:32].upper(), "size": 35, "gap": 24,
                 "color": "accent", "at": 0.24, "dur": 0.44, "dy": 30, "out": 99},
                {"kind": "pill", "text": brand.cta or "Batafsil", "size": 46, "gap": 62,
                 "at": 0.60, "dy": 50, "out": 99},
            ]}


def _beats(start: float, spans: list[float], family: str = "") -> list[tuple[float, float]]:
    """Turn a list of durations into beat-aligned [start, end] pairs.

    Aligned to *this family's* tempo, not a global one — a cut that lands on
    120 BPM while the bed plays 128 is worse than no alignment at all.
    """
    bpm = profile(family)["bpm"] if family else BPM
    beat = 60.0 / bpm
    # Accumulate in whole beats, not in rounded seconds. Rounding each span to
    # three decimals and adding them up drifts a couple of milliseconds per
    # scene, which is enough to walk the last cut off the pulse entirely.
    out: list[tuple[float, float]] = []
    cursor = round(start / beat)
    for span in spans:
        count = max(2, math.ceil(span / beat - 0.02))
        out.append((round(cursor * beat, 3), round((cursor + count) * beat, 3)))
        cursor += count
    return out


# --------------------------------------------------------------------------- #
# Families
# --------------------------------------------------------------------------- #

def statement(brand: Brand, *, kicker: str, hook: list[str], problem: list[str],
              diagnosis: list[str], formula_title: str,
              formula: list[tuple[str, str, str]], summary: list[str],
              headline: str) -> dict:
    """Hook → problem → diagnosis → formula → summary → CTA. The explainer."""
    spans = [3.5, 3.0, 3.5, 5.0, 2.5, 2.5]
    at = _beats(0.0, spans, "statement")
    rows = [{"kind": "row", "letter": lt, "word": wd, "desc": ds,
             "gap": 92 if i == 0 else 70, "at": 0.5 + i, "dy": 62}
            for i, (lt, wd, ds) in enumerate(formula[:3])]
    scenes = [
        {"at": list(at[0]), "transition": "none",
         **({"prop": {"src": brand.prop(0), "x": 500, "y": 150, "w": 800, "rot": -8, "drift": 22}}
            if brand.prop(0) else {}),
         "lines": [
             {"kind": "kicker", "text": kicker, "size": 32, "color": "brand", "at": 0.10, "dur": 0.44, "dy": 26},
             {"kind": "display", "text": hook[0], "size": 330, "gap": 40, "at": 0.42, "dy": 100, "scaleFrom": 1.15},
             {"kind": "serif", "text": hook[1], "size": 148, "gap": 14, "at": 0.78, "dy": 60},
             {"kind": "display", "text": hook[2], "size": 158, "gap": 22, "at": 1.06, "dy": 76, "scaleFrom": 1.10},
         ]},
        {"at": list(at[1]), "transition": "whip", "lines": [
            {"kind": "serif", "text": problem[0], "size": 118, "color": "muted", "at": 0.02, "dy": 46},
            {"kind": "display", "text": problem[1], "size": 150, "gap": 26, "at": 0.24, "dy": 80,
             "scaleFrom": 1.10, "strike": True, "strikeAt": 0.81},
            {"kind": "display", "text": problem[2], "size": 150, "gap": 16, "color": "accent",
             "at": 1.62, "dy": 70, "scaleFrom": 1.10},
        ]},
        {"at": list(at[2]), "transition": "whip",
         **({"prop": {"src": brand.prop(1), "x": 400, "y": 120, "w": 880, "rot": 6, "drift": 26}}
            if brand.prop(1) else {}),
         "lines": [
             {"kind": "serif", "text": diagnosis[0], "size": 118, "color": "muted", "at": 0.02, "dy": 46},
             {"kind": "display", "text": diagnosis[1], "size": 268, "gap": 10, "color": "accent",
              "glow": 80, "at": 0.26, "dy": 104, "scaleFrom": 1.18, "blur": 22},
             {"kind": "display", "text": diagnosis[2], "size": 150, "gap": 14, "at": 0.62, "dy": 66},
         ]},
        {"at": list(at[3]), "transition": "whip",
         **({"prop": {"src": brand.prop(2), "x": 545, "y": 1165, "w": 700, "rot": -6,
                      "drift": 18, "opacity": 0.95}} if brand.prop(2) else {}),
         "lines": [
             {"kind": "kicker", "text": formula_title, "size": 32, "color": "brand", "at": 0.02, "dur": 0.42, "dy": 26},
             {"kind": "rule", "width": 900, "gap": 38, "at": 0.14, "dur": 0.60},
             *rows,
         ]},
        {"at": list(at[4]), "transition": "whip",
         **({"prop": {"src": brand.prop(3), "x": 400, "y": 130, "w": 800, "drift": 24}}
            if brand.prop(3) else {}),
         "lines": [
             {"kind": "display", "text": summary[0], "size": 190, "at": 0.02, "dy": 92, "scaleFrom": 1.12},
             {"kind": "serif", "text": summary[1], "size": 115, "gap": 26, "at": 0.36, "dy": 62},
         ]},
        _cta(at[5][0], at[5][1], brand, headline),
    ]
    return _shell("statement", brand, at[-1][1], scenes, mark_until=at[5][0])


def sanoq(brand: Brand, *, title: str, subtitle: str,
          items: list[tuple[str, str, str]], headline: str) -> dict:
    """Numbered list. Centred, ghost numerals, alternating slide direction."""
    items = items[:6]
    at = _beats(0.0, [2.5] + [3.0] * len(items) + [2.5], "sanoq")
    scenes = [{"at": list(at[0]), "transition": "none", "lines": [
        {"kind": "kicker", "text": brand.mark[:32].upper(), "size": 32, "color": "brand",
         "at": 0.08, "dur": 0.40, "entry": "rise", "dy": 24},
        {"kind": "display", "text": title, "size": 230, "gap": 44, "at": 0.34, "scaleFrom": 0.72},
        {"kind": "serif", "text": subtitle, "size": 74, "gap": 30, "at": 0.66, "entry": "rise", "dy": 40},
    ]}]
    for i, (head, wrong, right) in enumerate(items):
        scenes.append({"at": list(at[i + 1]), "ghost": f"{i + 1:02d}",
                       "transition": "slide", "from": "right" if i % 2 == 0 else "left",
                       "lines": [
                           {"kind": "display", "text": head, "size": 128, "at": 0.10, "scaleFrom": 0.78},
                           {"kind": "body", "text": wrong, "size": 52, "gap": 34, "color": "muted",
                            "at": 0.40, "entry": "rise", "dy": 34},
                           {"kind": "body", "text": right, "size": 52, "gap": 14, "color": "accent",
                            "at": 0.70, "entry": "rise", "dy": 34},
                       ]})
    scenes.append(_cta(at[-1][0], at[-1][1], brand, headline))
    return _shell("sanoq", brand, at[-1][1], scenes, align="center", mark_until=at[-1][0])


def taqqoslash(brand: Brand, *, title: list[str],
               pairs: list[dict], headline: str) -> dict:
    """Split screen: wrong on top, right below. Wipe between."""
    pairs = pairs[:3]
    at = _beats(0.0, [3.0] + [5.5] * len(pairs) + [3.0], "taqqoslash")
    palette = brand.palette
    palette.setdefault("wrong", "#1A1F26")
    palette.setdefault("wrongInk", "#8A97A3")
    palette.setdefault("right", "#0E3A34")
    scenes = [{"at": list(at[0]), "align": "center", "transition": "none", "lines": [
        {"kind": "kicker", "text": brand.mark[:32].upper(), "size": 32, "color": "brand",
         "at": 0.08, "dur": 0.40, "dy": 24},
        {"kind": "display", "text": title[0], "size": 168, "gap": 40, "at": 0.34, "dy": 80},
        {"kind": "serif", "text": title[1], "size": 108, "gap": 22, "at": 0.66, "dy": 50},
    ]}]
    for i, pair in enumerate(pairs):
        scenes.append({
            "at": list(at[i + 1]), "layout": "split", "transition": "wipe",
            "wipeFrom": "left" if i % 2 == 0 else "right",
            "columns": [
                {"bg": "wrong", "align": "left", "valign": "center", "pad": 90, "lines": [
                    {"kind": "kicker", "text": pair["wrong_label"], "size": 30, "color": "wrongInk",
                     "at": 0.34, "dur": 0.40, "dy": 22},
                    {"kind": "display", "text": pair["wrong"], "size": 104, "gap": 26,
                     "color": "wrongInk", "at": 0.52, "dy": 46,
                     "strike": True, "strikeAt": 0.55, "strikeColor": "wrongInk"},
                ]},
                {"bg": "right", "align": "left", "valign": "center", "pad": 90, "lines": [
                    {"kind": "kicker", "text": pair["right_label"], "size": 30, "color": "accent",
                     "at": 1.00, "dur": 0.40, "dy": 22},
                    *[{"kind": "body", "text": line, "size": 54, "gap": 24 if j == 0 else 10,
                       "at": 1.18 + j * 0.16, "dy": 32}
                      for j, line in enumerate(pair["right"][:3])],
                ]},
            ]})
    scenes.append(_cta(at[-1][0], at[-1][1], brand, headline))
    return _shell("taqqoslash", brand, at[-1][1], scenes, mark_until=at[-1][0])


def savol(brand: Brand, *, question: list[str], options: list[str], correct: int,
          reasons: list[tuple[str, str]], headline: str,
          title: list[str] | None = None) -> dict:
    """Question → countdown → reveal → why. The interactive pillar."""
    options = options[:3]
    title = title or ["Qaysi javob", "to'g'ri?"]
    at = _beats(0.0, [2.5, 5.0, 3.0, 4.0, 3.0, 2.5], "savol")
    letters = "ABC"
    scenes = [
        {"at": list(at[0]), "transition": "none", "lines": [
            {"kind": "kicker", "text": brand.mark[:32].upper(), "size": 32, "color": "brand",
             "at": 0.08, "dur": 0.42, "dy": 24},
            {"kind": "display", "text": title[0], "size": 168, "gap": 42, "at": 0.32, "dy": 78},
            {"kind": "display", "text": title[1], "size": 168, "gap": 8, "color": "accent",
             "glow": 70, "at": 0.56, "dy": 78},
        ]},
        {"at": list(at[1]), "transition": "whip", "align": "left", "lines": [
            {"kind": "kicker", "text": "SAVOL", "size": 30, "color": "brand", "at": 0.04, "dur": 0.40, "dy": 22},
            *[{"kind": "serif", "text": line, "size": 72, "gap": 24 if j == 0 else 6,
               "at": 0.20 + j * 0.12, "dy": 40} for j, line in enumerate(question[:2])],
            *[{"kind": "option", "letter": letters[j], "text": opt,
               "gap": 58 if j == 0 else 24, "at": 0.70 + j * 0.40, "dy": 44}
              for j, opt in enumerate(options)],
        ]},
        {"at": list(at[2]), "transition": "cut", "align": "center", "lines": [
            {"kind": "kicker", "text": "O'YLANG", "size": 34, "color": "brand", "at": 0.04, "dur": 0.40, "dy": 22},
            {"kind": "number", "from": 3, "to": 0, "size": 460, "glow": 110, "gap": 30,
             "at": 0.16, "dur": 2.4, "ease": "linear", "entry": "scale", "scaleFrom": 0.7},
        ]},
        {"at": list(at[3]), "transition": "whip", "align": "left", "lines": [
            {"kind": "kicker", "text": "JAVOB", "size": 30, "color": "accent", "at": 0.04, "dur": 0.40, "dy": 22},
            *[{"kind": "option", "letter": letters[j], "text": opt,
               "state": "right" if j == correct else "wrong",
               "gap": 44 if j == 0 else 24,
               "at": 0.16 + j * 0.10 + (0.18 if j == correct else 0),
               "dy": 46 if j == correct else 30,
               **({"entry": "scale", "scaleFrom": 0.9} if j == correct else {})}
              for j, opt in enumerate(options)],
        ]},
        {"at": list(at[4]), "transition": "whip", "align": "left", "lines": [
            {"kind": "kicker", "text": f"NEGA {letters[correct]}", "size": 30, "color": "brand",
             "at": 0.04, "dur": 0.40, "dy": 22},
            {"kind": "rule", "width": 900, "gap": 30, "at": 0.14, "dur": 0.55},
            *[{"kind": "row", "letter": str(j + 1), "word": word, "desc": desc,
               "gap": 62 if j == 0 else 46, "at": 0.34 + j * 0.38, "dy": 52,
               "letterSize": 110, "letterWidth": 96, "wordSize": 68, "descSize": 36}
              for j, (word, desc) in enumerate(reasons[:3])],
        ]},
        _cta(at[5][0], at[5][1], brand, headline),
    ]
    return _shell("savol", brand, at[-1][1], scenes, align="center", mark_until=at[5][0])


def raqam(brand: Brand, *, title: str, stats: list[dict], headline: str) -> dict:
    """One big number per scene, counted up. The short story format."""
    stats = stats[:3]
    at = _beats(0.0, [2.5] + [3.0] * len(stats) + [3.0], "raqam")
    scenes = [{"at": list(at[0]), "transition": "none", "lines": [
        {"kind": "kicker", "text": brand.mark[:32].upper(), "size": 32, "color": "brand",
         "at": 0.10, "dur": 0.44, "dy": 24},
        {"kind": "display", "text": title, "size": 150, "gap": 44, "at": 0.38, "dy": 76},
    ]}]
    for i, stat in enumerate(stats):
        scenes.append({"at": list(at[i + 1]), "ghost": f"{i + 1:02d}", "ghostOpacity": 0.05,
                       "transition": "cut", "lines": [
                           {"kind": "number", "from": 0, "to": int(stat["value"]),
                            "suffix": stat.get("suffix", ""), "size": 420, "glow": 90,
                            "at": 0.06, "dur": 1.2},
                           {"kind": "body", "text": stat["label"], "size": 54, "gap": 30,
                            "color": "muted", "at": 0.76, "dy": 36},
                       ]})
    scenes.append(_cta(at[-1][0], at[-1][1], brand, headline))
    return _shell("raqam", brand, at[-1][1], scenes, align="center", mark_until=at[-1][0])


def isbot(brand: Brand, *, photo: str | None, badge: str, quote: list[str],
          attribution: str, changed_title: str,
          changed: list[tuple[str, str, str]], headline: str) -> dict:
    """Student result: portrait, score badge, pull quote, what changed."""
    at = _beats(0.0, [4.0, 5.0, 4.0, 3.0], "isbot")
    hero = [{"kind": "kicker", "text": "O'QUVCHI NATIJASI", "size": 32, "color": "brand",
             "at": 0.10, "dur": 0.44, "dy": 24}]
    if photo:
        hero.append({"kind": "photo", "src": photo, "w": 560, "h": 700, "mask": "arch",
                     "ring": 6, "ringColor": "accent", "gap": 40, "at": 0.34,
                     "entry": "scale", "scaleFrom": 0.78})
    hero.append({"kind": "badge", "text": badge, "size": 54, "gap": 40, "at": 0.90, "dy": 40})
    scenes = [
        {"at": list(at[0]), "transition": "none", "lines": hero},
        {"at": list(at[1]), "transition": "whip", "align": "left", "lines": [
            *[{"kind": "serif", "text": line, "size": 96, "gap": 0 if j == 0 else 12,
               "at": 0.10 + j * 0.24, "dy": 52} for j, line in enumerate(quote[:4])],
            {"kind": "rule", "width": 420, "gap": 46, "at": 1.10, "dur": 0.55},
            {"kind": "body", "text": attribution, "size": 46, "gap": 28, "color": "muted",
             "at": 1.30, "dy": 30},
        ]},
        {"at": list(at[2]), "transition": "whip", "align": "left", "lines": [
            {"kind": "kicker", "text": changed_title, "size": 32, "color": "brand",
             "at": 0.06, "dur": 0.42, "dy": 24},
            {"kind": "rule", "width": 900, "gap": 34, "at": 0.18, "dur": 0.55},
            *[{"kind": "row", "letter": lt, "word": wd, "desc": ds,
               "gap": 78 if j == 0 else 62, "at": 0.44 + j * 0.60, "dy": 58}
              for j, (lt, wd, ds) in enumerate(changed[:3])],
        ]},
        _cta(at[3][0], at[3][1], brand, headline),
    ]
    return _shell("isbot", brand, at[-1][1], scenes, align="center", mark_until=at[3][0])




def ustoz(brand: Brand, *, title: str, subtitle: str, caption: str,
          footage: str, headline: str) -> dict:
    """Real lesson footage, masked into the brand system.

    The only family that puts a person on screen. A centre sells its teachers
    more than its curriculum, and until this existed the footage they already
    shoot sat unused while every clip was type on a background.
    """
    at = _beats(0.0, [3.0, 8.0, 3.0], "ustoz")
    scenes = [
        {"at": list(at[0]), "transition": "none", "lines": [
            {"kind": "kicker", "text": brand.mark[:32].upper(), "size": 32, "color": "brand",
             "at": 0.08, "dur": 0.42, "dy": 24},
            {"kind": "display", "text": title, "size": 168, "gap": 40, "at": 0.32, "dy": 78},
            {"kind": "serif", "text": subtitle, "size": 112, "gap": 18, "at": 0.60, "dy": 50},
        ]},
        {"at": list(at[1]), "transition": "whip", "lines": [
            {"kind": "video", "src": footage, "w": 620, "h": 900, "mask": "arch",
             "ring": 6, "ringColor": "accent", "start": 0.5, "at": 0.10,
             "entry": "scale", "scaleFrom": 0.82, "out": 99},
            {"kind": "body", "text": caption, "size": 50, "gap": 44, "color": "muted",
             "at": 0.70, "dy": 34, "out": 99},
        ]},
        _cta(at[2][0], at[2][1], brand, headline),
    ]
    return _shell("ustoz", brand, at[-1][1], scenes, align="center", mark_until=at[2][0])


def uzluksiz(brand: Brand, *, opening: str, middle: str, build: str, punch: str,
             tagline: str, headline: str) -> dict:
    """One scene, no cuts. Copy accumulates; nothing ever leaves.

    Every other family is cut-driven. This one holds a single frame for its
    whole length and lets the background drift — the register a brand post
    wants, rather than the register an explainer wants. `headline` is unused;
    the closing line is the punch itself.
    """
    duration = 17.0
    lines = [
        {"kind": "kicker", "text": brand.mark[:32].upper(), "size": 32, "color": "brand",
         "at": 0.6, "dur": 0.9, "dy": 20, "out": 99},
        {"kind": "display", "text": opening, "size": 168, "gap": 40, "at": 1.6, "dur": 1.1,
         "dy": 60, "scaleFrom": 1.06, "out": 99},
        {"kind": "serif", "text": middle, "size": 116, "gap": 18, "at": 3.6, "dur": 1.1,
         "dy": 46, "out": 99},
        {"kind": "display", "text": build, "size": 168, "gap": 22, "at": 6.0, "dur": 1.1,
         "dy": 60, "scaleFrom": 1.06, "out": 99},
        {"kind": "display", "text": punch, "size": 168, "gap": 6, "color": "accent",
         "glow": 70, "at": 8.0, "dur": 1.2, "dy": 60, "scaleFrom": 1.06, "out": 99},
        {"kind": "rule", "width": 820, "gap": 54, "at": 10.6, "dur": 1.2, "out": 99},
        {"kind": "body", "text": tagline, "size": 48, "gap": 30, "color": "muted",
         "at": 11.6, "dur": 1.0, "dy": 28, "out": 99},
        {"kind": "pill", "text": brand.cta or "Batafsil", "size": 46, "gap": 54,
         "at": 13.6, "dur": 1.0, "dy": 40, "out": 99},
    ]
    scene: dict[str, Any] = {"at": [0.0, duration], "transition": "none",
                             "align": "left", "lines": lines}
    if brand.prop(1):
        scene["prop"] = {"src": brand.prop(1), "x": 430, "y": 110, "w": 900,
                         "rot": 4, "drift": 34, "rotDrift": 7, "scaleFrom": 0.88}
    return _shell("uzluksiz", brand, duration, [scene],
                  mark_until=99, extra={"flash": 0})


def dastur(brand: Brand, *, title: str, subtitle: str,
           groups: list[dict], headline: str) -> dict:
    """A timetable or price list. The announcement an education centre repeats."""
    groups = groups[:2]
    at = _beats(0.0, [3.0] + [5.0] * len(groups) + [3.0], "dastur")
    scenes = [{"at": list(at[0]), "align": "center", "transition": "none", "lines": [
        {"kind": "kicker", "text": brand.mark[:32].upper(), "size": 32, "color": "brand",
         "at": 0.08, "dur": 0.42, "dy": 24},
        {"kind": "display", "text": title, "size": 210, "gap": 40, "at": 0.32, "dy": 80},
        {"kind": "serif", "text": subtitle, "size": 104, "gap": 18, "at": 0.60, "dy": 46},
    ]}]
    for index, group in enumerate(groups):
        scenes.append({"at": list(at[index + 1]), "transition": "whip", "align": "left", "lines": [
            {"kind": "kicker", "text": group["title"], "size": 30, "color": "brand",
             "at": 0.04, "dur": 0.40, "dy": 22},
            {"kind": "rule", "width": 900, "gap": 26, "at": 0.14, "dur": 0.55},
            {"kind": "table", "gap": 52, "at": 0.34, "dy": 52,
             "leftSize": 54, "rightSize": 64,
             "rows": [{"left": r["left"], "right": r["right"]} for r in group["rows"][:4]]},
        ]})
    scenes.append(_cta(at[-1][0], at[-1][1], brand, headline))
    return _shell("dastur", brand, at[-1][1], scenes, mark_until=at[-1][0])


def muddat(brand: Brand, *, kicker: str, pressure: str, count_from: int, count_to: int,
           count_label: str, date_lead: str, date: str, date_tail: str,
           headline: str) -> dict:
    """Urgency: a number falling, then the date it runs out.

    `raqam` counts *up* to impress. This counts *down* to push — same line
    kind, opposite rhetorical move, so it gets its own family rather than a
    flag on that one.
    """
    at = _beats(0.0, [2.5, 3.5, 3.0, 3.0], "muddat")
    scenes = [
        {"at": list(at[0]), "transition": "none", "lines": [
            {"kind": "kicker", "text": kicker, "size": 32, "color": "brand",
             "at": 0.08, "dur": 0.40, "dy": 24},
            {"kind": "display", "text": pressure, "size": 190, "gap": 40, "at": 0.30,
             "dy": 78, "scaleFrom": 1.12},
        ]},
        {"at": list(at[1]), "transition": "cut", "lines": [
            {"kind": "number", "from": count_from, "to": count_to, "size": 480,
             "glow": 120, "at": 0.06, "dur": 1.6, "entry": "scale", "scaleFrom": 0.72},
            {"kind": "display", "text": count_label, "size": 108, "gap": 26, "at": 1.30, "dy": 46},
        ]},
        {"at": list(at[2]), "transition": "slide", "from": "right", "lines": [
            {"kind": "serif", "text": date_lead, "size": 108, "color": "muted", "at": 0.06, "dy": 44},
            {"kind": "display", "text": date, "size": 168, "gap": 16, "color": "accent",
             "glow": 80, "at": 0.28, "dy": 66, "scaleFrom": 1.10},
            {"kind": "body", "text": date_tail, "size": 52, "gap": 26, "color": "muted",
             "at": 0.56, "dy": 32},
        ]},
        _cta(at[3][0], at[3][1], brand, headline),
    ]
    return _shell("muddat", brand, at[-1][1], scenes, align="center",
                  mark_until=at[3][0], extra={"flash": 0.16})


BUILDERS = {
    "statement": statement, "sanoq": sanoq, "taqqoslash": taqqoslash,
    "savol": savol, "raqam": raqam, "isbot": isbot,
    "ustoz": ustoz, "uzluksiz": uzluksiz, "dastur": dastur, "muddat": muddat,
}
