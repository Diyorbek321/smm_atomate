"""Composes a promo script out of reusable *scene archetypes*.

:mod:`app.services.promo_families` authors whole videos: ten functions, each
one a complete clip from hook to sign-off. That is why every educational clip
looks like every other educational clip — the family *is* the structure, and
there are ten of them.

This module inverts that. An archetype (``assets/promo/scenes/*.json``) authors
*one scene* — a stat capsule, a price table, a quote — and a script is a
sequence of them. Ten archetypes compose into far more than ten videos, and a
model choosing a sequence is choosing structure without ever emitting geometry.

The layout stays authored, which is the whole point of both engines: the model
picks archetypes by name and supplies copy, never coordinates.

The output is a script for :func:`app.services.promo.render_promo`, identical
in shape to what the families emit, so both paths render through one template.

Ported from the ``promo/`` lab (``make.mjs``), which is where the archetype
system was worked out against real footage.
"""

from __future__ import annotations

import json
import re
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.services.music import energy_for
from app.services.promo_families import Brand
from app.utils.text import fingerprint

log = get_logger(__name__)

SCENES_DIR = Path(__file__).resolve().parent.parent / "assets" / "promo" / "scenes"

#: The lab names moods in Uzbek; the bed knows four progressions. Mapping here
#: rather than renaming the archetypes keeps the two vocabularies independent —
#: a new mood is a line in this table, not a migration.
MOODS: dict[str, str] = {
    "qorongu": "calm",      # reflective minor — the default
    "minimal": "calm",
    "tezkor": "hopeful",    # brisk, forward-leaning
    "iliq": "warm",
    "hikoya": "warm",
}

DEFAULT_BPM = 118

#: Delivery rate the narration is written against. The silent fallback below
#: estimates scene length from it, so it has to match whatever eventually
#: speaks the lines or every scene lands at the wrong length.
WPM = 150

#: Breathing room after a narrated line before the cut.
TAIL = 0.22

#: `{{key}}` or `{{key|fallback}}`.
_SOLO = re.compile(r"^\{\{([^}|]+)(?:\|([^}]*))?\}\}$")
_ANY = re.compile(r"\{\{([^}|]+)(?:\|([^}]*))?\}\}")

#: Archetype bookkeeping — useful to the model, meaningless to the renderer.
_META_KEYS = ("use", "slot", "needs", "desc", "clip", "say", "tail", "silent")

#: Vowels carry the syllable, so they carry the time. Used to spread a written
#: line across a known duration when no real word timing exists.
_VOWELS = frozenset("aeiouAEIOUoO")


@cache
def _archetype(name: str) -> dict[str, Any]:
    path = SCENES_DIR / f"{name}.json"
    if not path.is_file():
        raise ConfigurationError(
            f"«{name}» arxetipi topilmadi. Mavjudlari: {', '.join(archetype_names())}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def archetype_names() -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in SCENES_DIR.glob("*.json")))


def catalogue() -> list[dict[str, Any]]:
    """What each archetype is for and what copy it needs.

    This is what a model is shown when it picks a sequence; the archetype files
    are the single source of truth for it, so a new scene type is one JSON file
    and nothing else.
    """
    out = []
    for name in archetype_names():
        spec = _archetype(name)
        out.append({
            "name": name,
            "needs": list(spec.get("needs", [])),
            "desc": spec.get("desc", ""),
        })
    return out


def _maybe_number(value: Any) -> Any:
    """A solo placeholder that resolved to a numeric string becomes a number.

    ``{"to": "{{s.to}}"}`` feeds a counter that animates from 0. Left as the
    string ``"83"`` it renders once and never counts.
    """
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        number = float(value)
    except ValueError:
        return value
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return value
    return int(number) if number.is_integer() else number


def _say_weight(word: str) -> float:
    vowels = sum(1 for c in word if c in _VOWELS)
    return 1 + 1.6 * vowels + 0.30 * (len(word) - vowels)


def spread_words(text: str, duration: float) -> list[dict[str, Any]]:
    """Word timings for a line nobody measured.

    Real timings come from the speech synthesiser. Without it — and a clip is
    still worth rendering without it — the line is spread across the scene by
    how long each word takes to say. Scenes are short (2–6 s), so the error
    never accumulates far enough to look wrong.

    A word wrapped in asterisks is marked for emphasis and keeps no asterisks.
    """
    tokens = [t for t in str(text).split() if t]
    weights = [_say_weight(re.sub(r"[*.,!?—:;]", "", t)) for t in tokens]
    total = sum(weights) or 1.0
    out, acc = [], 0.0
    for token, weight in zip(tokens, weights, strict=True):
        out.append({
            "w": token.replace("*", ""),
            "at": round(acc / total * duration, 3),
            "b": token.startswith("*") or token.endswith("*"),
        })
        acc += weight
    return out


class _Composer:
    """One build. Holds the job so the resolvers stay small."""

    def __init__(self, job: dict[str, Any], brand: Brand,
                 timing: list[dict[str, Any]] | None, clips: list[dict[str, Any]] | None):
        self.job = job
        self.brand = brand
        #: Measured speech, one entry per `say` line, in the order they are
        #: spoken — a list rather than a mapping because that is what the
        #: synthesiser emits and `say` is already an index into it.
        self.timing = list(timing or [])
        self.clips = clips or []
        self.missing: set[str] = set()
        self.silent: list[int] = []
        self.text: dict[str, Any] = job.get("text") or {}
        self.say: list[str] = list(job.get("say") or [])
        #: What `{{brand.*}}` can see. A dict rather than the dataclass so an
        #: archetype cannot reach into behaviour it has no business calling.
        self.brand_view: dict[str, Any] = {
            "mark": brand.mark, "cta": brand.cta, "sign": brand.mark,
            **brand.palette,
        }

    # -- placeholders ------------------------------------------------------

    def lookup(self, key: str, clip: str | None, slot: str | None,
               item: Any) -> Any:
        if key == "clip":
            return clip
        namespace, _, name = key.partition(".")
        if namespace == "text":
            return self.text.get(name)
        if namespace == "brand":
            return self.brand_view.get(name)
        # `s.` is this scene's own slot. An archetype does not know which slot
        # it was placed in, so this is how it reaches its copy — and how one
        # archetype used twice in a video keeps its two texts apart.
        if namespace == "s":
            return (self.text.get(slot) or {}).get(name) if slot is not None else None
        if namespace == "item":
            if not name:
                return item.get("v", item) if isinstance(item, dict) else item
            return item.get(name) if isinstance(item, dict) else None
        return None

    def resolve(self, node: Any, clip: str | None, slot: str | None,
                item: Any = None) -> Any:
        if isinstance(node, str):
            return self._resolve_string(node, clip, slot, item)
        if isinstance(node, list):
            return [self.resolve(n, clip, slot, item) for n in node]
        if isinstance(node, dict):
            return {k: self.resolve(v, clip, slot, item) for k, v in node.items()}
        return node

    def _resolve_string(self, node: str, clip: str | None, slot: str | None,
                        item: Any) -> Any:
        if "{{" not in node:
            return node
        solo = _SOLO.match(node)
        if solo:
            value = self.lookup(solo.group(1).strip(), clip, slot, item)
            if value is None:
                value = solo.group(2)
            if value is None:
                self.missing.add(solo.group(1).strip())
                return ""
            return _maybe_number(value)

        def one(match: re.Match[str]) -> str:
            value = self.lookup(match.group(1).strip(), clip, slot, item)
            if value is not None:
                return str(value)
            if match.group(2) is not None:
                return match.group(2)
            self.missing.add(match.group(1).strip())
            return ""

        return _ANY.sub(one, node)

    # -- lines -------------------------------------------------------------

    def expand_repeat(self, lines: list[dict[str, Any]] | None,
                      slot: str | None) -> list[dict[str, Any]]:
        """One authored row per list entry.

        The list length lives in the copy and the archetype does not know it,
        which is what lets a three-item list and a six-item list share one
        layout.
        """
        out: list[dict[str, Any]] = []
        for line in lines or []:
            if not line.get("repeat"):
                out.append(line)
                continue
            key = str(line["repeat"]).strip().removeprefix("{{").removesuffix("}}").strip()
            values = self.lookup(key, None, slot, None)
            if not isinstance(values, list):
                self.missing.add(key)
                continue
            stagger = line.get("stagger")
            for index, raw in enumerate(values):
                copy = json.loads(json.dumps(line))
                copy.pop("repeat", None)
                copy.pop("stagger", None)
                if stagger is not None and copy.get("at") is not None:
                    copy["at"] = round(copy["at"] + index * stagger, 3)
                copy["__item"] = ({**raw, "n": index + 1} if isinstance(raw, dict)
                                  else {"v": raw, "n": index + 1})
                out.append(copy)
        return out

    # -- scenes ------------------------------------------------------------

    def _voice(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        index = raw.get("say")
        if index is None or not isinstance(index, int) or index >= len(self.timing):
            return None
        return self.timing[index]

    def _duration(self, raw: dict[str, Any], index: int, voice: dict | None,
                  clip: dict | None) -> float:
        if raw.get("dur") is not None:
            return float(raw["dur"])
        if voice:
            return round(float(voice["dur"]) + float(raw.get("tail", TAIL)), 3)
        if raw.get("say") is not None:
            # No measured audio for this line. Rather than fail the whole clip,
            # estimate from the delivery rate and mark the scene silent: a
            # draft you can watch beats a render that never happened.
            words = len(str(self.say[raw["say"]] if raw["say"] < len(self.say) else "").split())
            if not words:
                raise ConfigurationError(
                    f"{index + 1}-sahna {raw['say']}-gapni so'rayapti, "
                    f"lekin ishda bunday gap yo'q"
                )
            self.silent.append(index + 1)
            return round(words / WPM * 60 + 0.6, 3)
        if clip:
            return float(clip["dur"])
        raise ConfigurationError(
            f"{index + 1}-sahna: na «clip», na «say», na «dur» berilgan"
        )

    def _karaoke_words(self, raw: dict[str, Any], voice: dict | None,
                       clip_index: int | None, duration: float) -> list | None:
        """Word timings for any karaoke line in this scene.

        Three sources, in descending order of truth: measured synthesiser
        output, a spoken line typed into the job (someone talks on camera and
        Whisper cannot be trusted with Uzbek), and — for a graphics-only clip
        with no audio yet — the narration text spread across the scene.
        """
        if voice:
            return voice["words"]
        speech = (self.job.get("speech") or {})
        if clip_index is not None and speech.get(clip_index) is not None:
            return spread_words(speech[clip_index], duration)
        if raw.get("say") is not None and raw["say"] < len(self.say):
            return spread_words(self.say[raw["say"]], duration)
        return None

    def _scene(self, ref: dict[str, Any], index: int,
               start: float) -> tuple[dict, float, str | None]:
        # The archetype is the base; the reference overrides it.
        raw = {**_archetype(ref["use"]), **ref} if ref.get("use") else dict(ref)
        slot = str(ref["slot"]) if ref.get("slot") is not None else str(index)

        clip_index = raw.get("clip")
        clip = None
        if clip_index is not None:
            if clip_index >= len(self.clips):
                raise ConfigurationError(
                    f"{index + 1}-sahna {clip_index}-kesimni so'rayapti, "
                    f"ishda faqat {len(self.clips)} ta bor"
                )
            clip = self.clips[clip_index]

        voice = self._voice(raw)
        duration = self._duration(raw, index, voice, clip)

        # Lines are resolved one at a time: a repeated row has to see its own
        # list entry, and only the expansion knows which that is.
        lines = self.expand_repeat(raw.get("lines"), slot)
        scene = self.resolve({**raw, "lines": None}, clip["video"] if clip else None, slot)
        scene["lines"] = [
            self.resolve({k: v for k, v in line.items() if k != "__item"},
                         clip["video"] if clip else None, slot, line.get("__item"))
            for line in lines
        ]
        for key in _META_KEYS:
            scene.pop(key, None)

        # The archetype knows the layout but not the words; the job knows the
        # words but not the timing. This is where they meet.
        words = self._karaoke_words(raw, voice, clip_index, duration)
        if words:
            for pane in [scene, *(scene.get("columns") or [])]:
                for line in pane.get("lines") or []:
                    if line.get("kind") == "karaoke" and not line.get("words"):
                        line["words"] = words

        scene["at"] = [round(start, 3), round(start + duration, 3)]
        # Whatever plays under this scene: the synthesised line, or the cut's
        # own audio when someone is talking on camera.
        source = voice["src"] if voice else (
            clip["audio"] if clip and raw.get("silent") is not True else None
        )
        return scene, duration, source

    # -- script ------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        refs = self.job.get("scenes") or []
        if not refs:
            raise ConfigurationError("ishda birorta ham sahna yo'q")

        scenes: list[dict[str, Any]] = []
        voice_track: list[dict[str, Any]] = []
        clock = 0.0
        for index, ref in enumerate(refs):
            scene, duration, source = self._scene(ref, index, clock)
            if source:
                voice_track.append({"src": source, "at": round(clock, 3)})
            scenes.append(scene)
            clock += duration

        if self.missing:
            raise ConfigurationError(
                "matn maydonlari yetishmayapti: " + ", ".join(sorted(self.missing))
            )
        if self.silent:
            log.warning("promo_scenes_silent", scenes=self.silent, name=self.job.get("name"))

        return self._shell(scenes, voice_track, round(clock, 3))

    def _shell(self, scenes: list[dict], voice: list[dict], duration: float) -> dict[str, Any]:
        job, brand = self.job, self.brand
        script: dict[str, Any] = {
            "name": job.get("name", "promo"),
            "family": "arxetip",
            "duration": duration,
            "fps": int(job.get("fps", 30)),
            "size": list(job.get("size", [1080, 1920])),
            "palette": brand.palette,
            "glow": job.get("glow", brand.glow()),
            "align": job.get("align", "left"),
            "flash": job.get("flash", 0.14),
            "markColor": job.get("markColor", brand.palette.get("muted", "")),
            "music": self._music(duration),
            "scenes": scenes,
        }
        if job.get("vignette"):
            script["vignette"] = job["vignette"]
        if brand.mark:
            script["mark"] = {
                "text": brand.mark, "from": 0.8,
                "until": round(scenes[-1]["at"][0] - 0.1, 3),
            }
        # render_promo does not mix a voice track yet; carried so the speech
        # layer has the cut points it needs without rebuilding the script.
        if voice:
            script["voice"] = voice
        return script

    def _music(self, duration: float) -> dict[str, Any]:
        mood = MOODS.get(str(self.job.get("mood", "")), "calm")
        return {
            "bpm": int(self.job.get("bpm", DEFAULT_BPM)),
            "mood": mood,
            "energy": energy_for(mood),
            "key_shift": self.brand.key_shift,
            # Two clips for one business, same mood, should not open on the
            # same chord. The name is the only thing guaranteed to differ.
            "rotation": fingerprint(str(self.job.get("name", ""))) % 4,
        }


def build_script(job: dict[str, Any], brand: Brand, *,
                 timing: list[dict[str, Any]] | None = None,
                 clips: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Assemble one promo script from a job.

    ``job`` carries the sequence and the copy, nothing about layout::

        {"name": "...", "mood": "tezkor",
         "scenes": [{"use": "stat", "slot": "s0", "say": 0}, ...],
         "say":   ["narration for scene 0", ...],
         "text":  {"s0": {"label": "...", "to": 83}, ...}}

    ``timing`` is measured speech per ``say`` line (``{src, dur, words}``);
    without it scene lengths are estimated and the clip renders mute. ``clips``
    supplies cut footage as ``{video, audio, dur}`` for jobs that have any.
    """
    script = _Composer(job, brand, timing, clips).build()
    log.info("promo_script_composed", name=script["name"], scenes=len(script["scenes"]),
             seconds=script["duration"], mood=script["music"]["mood"])
    return script
