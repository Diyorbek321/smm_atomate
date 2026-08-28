"""A gate on promo copy, run before anything is rendered.

The clip is the most expensive artefact this system produces — a browser draws
six hundred frames, which is minutes of CPU — and until now it was the only one
with no editorial check at all. :class:`app.agents.editor.EditorAgent` guards
the content pipeline, but it is built around captions: its rules start at a
twelve-word minimum, which is meaningless for a line of display type.

So the checks here are the ones that actually ship a broken clip: a blank line,
the same sentence twice, a field the model echoed instead of filling. They are
deterministic and cost nothing, which matters because the alternative — finding
out after the render — costs two minutes and a wasted queue slot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.similarity import tokens

#: Text kinds a viewer reads. Props, rules and photos carry no copy.
TEXT_KINDS = ("display", "serif", "kicker", "body", "option", "row", "table", "pill", "badge")

#: Signs the model returned scaffolding rather than copy.
PLACEHOLDERS = re.compile(
    r"(lorem ipsum|\btodo\b|\bxxx+\b|\{\{?\s*\w+\s*\}?\}|<[a-z_]+>|placeholder|matn shu yerda)",
    re.IGNORECASE,
)

#: Below this a display line is not a word, it is a leftover.
MIN_DISPLAY_CHARS = 2

#: Words per second a viewer can take from large display type.
#:
#: Not a general reading speed — this is short, high-contrast copy on a phone,
#: and the number is calibrated against the clips already shipped rather than
#: guessed: the densest of them runs at five words per second. Six is the point
#: past which copy is longer than the layout it was written for, which is what
#: this is actually detecting.
WORDS_PER_SECOND = 6.0

#: A scene must at least finish assembling, plus a beat to register it.
SETTLE_MARGIN = 0.4


@dataclass(slots=True)
class Issue:
    severity: str            # "block" | "warn"
    detail: str

    @property
    def blocking(self) -> bool:
        return self.severity == "block"


def _texts(script: dict) -> list[tuple[int, str, str]]:
    """Every readable string, as (scene number, kind, text)."""
    found: list[tuple[int, str, str]] = []
    for index, scene in enumerate(script.get("scenes", []), start=1):
        for pane in (scene.get("columns") or [scene]):
            for line in pane.get("lines", []):
                kind = line.get("kind", "display")
                if kind not in TEXT_KINDS:
                    continue
                if kind == "row":
                    for field in ("letter", "word", "desc"):
                        found.append((index, kind, str(line.get(field, ""))))
                elif kind == "table":
                    for row in line.get("rows", []):
                        found.append((index, kind, str(row.get("left", ""))))
                        found.append((index, kind, str(row.get("right", ""))))
                else:
                    found.append((index, kind, str(line.get("text", ""))))
    return found


def _scene_words(scene: dict) -> int:
    words = 0
    for pane in (scene.get("columns") or [scene]):
        for line in pane.get("lines", []):
            kind = line.get("kind", "display")
            if kind not in TEXT_KINDS:
                continue
            if kind == "row":
                words += len(f"{line.get('word', '')} {line.get('desc', '')}".split())
            elif kind == "table":
                for row in line.get("rows", []):
                    words += len(f"{row.get('left', '')} {row.get('right', '')}".split())
            else:
                words += len(str(line.get("text", "")).split())
    return words


def _settle(scene: dict) -> float:
    latest = 0.0
    for pane in (scene.get("columns") or [scene]):
        for line in pane.get("lines", []):
            latest = max(latest, float(line.get("at", 0.0)) + float(line.get("dur", 0.52)))
    return latest


def reading_time(scene: dict) -> float:
    """Seconds this scene needs before a viewer can finish it.

    Reading runs *concurrently* with the reveal — lines land one by one and are
    read as they land — so this is the longer of two constraints, not their
    sum: the scene has to finish assembling, and it has to leave enough total
    time for the words in it.
    """
    return max(_settle(scene) + SETTLE_MARGIN, _scene_words(scene) / WORDS_PER_SECOND)


#: The shortest common opening that counts as the same word. Uzbek is
#: agglutinative — a clip about "Backend dasturlash kursiga qabul" writes
#: "Backend kursi", and a brief about "xatolar" is answered with "xato" — so
#: whole-word matching says a perfectly on-topic script ignored its brief.
#: Below this many characters the words have to match outright, or "bir" and
#: "biznes" would count as the same subject.
MIN_STEM = 4


def _same_word(left: str, right: str) -> bool:
    """Is one of these the other with a suffix on it?

    Comparing a fixed-length prefix of both fails the moment one side is the
    shorter word: `xato` and `xatolar` share a stem, but `xato`[:6] is `xato`
    and `xatolar`[:6] is `xatola`. Comparing over the shorter of the two is
    what actually asks the question.
    """
    shared = min(len(left), len(right))
    if shared < MIN_STEM:
        return left == right
    return left[:shared] == right[:shared]


def off_topic(script: dict, topic: str) -> bool:
    """Does none of this copy mention what the clip was asked to be about?

    Deliberately generous: one surviving stem anywhere in the script is
    enough. The question is not whether the copy is *good*, it is whether the
    model wrote about the requested subject at all — and until the brief moved
    to the end of the prompt, it routinely did not: asked for a clip about a
    backend course it returned the knowledge base's own subject, three times
    out of three, on both models.

    A topic with no content words (all stop words, or empty) is unanswerable,
    so it passes rather than blocking a clip on a heuristic.
    """
    wanted = tokens(topic)
    if not wanted:
        return False
    written = tokens(" ".join(text for _, _, text in _texts(script)))
    return not any(_same_word(word, other) for word in wanted for other in written)


def inspect(script: dict) -> list[Issue]:
    """Everything wrong with this script's copy, worst first."""
    issues: list[Issue] = []
    entries = _texts(script)

    for scene, kind, text in entries:
        stripped = text.strip()
        if not stripped:
            issues.append(Issue("block", f"{scene}-sahna: bo'sh {kind} qatori"))
            continue
        if PLACEHOLDERS.search(stripped):
            issues.append(Issue("block", f"{scene}-sahna: to'ldirilmagan matn «{stripped[:30]}»"))
        if kind == "display" and len(stripped) < MIN_DISPLAY_CHARS:
            issues.append(Issue("block", f"{scene}-sahna: juda qisqa sarlavha «{stripped}»"))

    # The same sentence twice reads as a mistake even when it is deliberate,
    # and models repeat themselves when a schema asks for three of something.
    meaningful = [t.strip().casefold() for _, kind, t in entries
                  if kind not in ("kicker", "row") and len(t.strip()) > 8]
    for text in set(meaningful):
        if meaningful.count(text) > 1:
            issues.append(Issue("warn", f"takrorlangan qator «{text[:36]}»"))

    for index, scene in enumerate(script.get("scenes", []), start=1):
        held = float(scene["at"][1]) - float(scene["at"][0])
        needed = reading_time(scene)
        if needed > held + 0.05:
            issues.append(Issue(
                "warn",
                f"{index}-sahna qisqa: {held:.1f}s, o'qish uchun {needed:.1f}s kerak",
            ))

    if not any(kind == "pill" for _, kind, _ in entries):
        issues.append(Issue("warn", "harakatga chaqiruv (pill) yo'q"))

    issues.sort(key=lambda i: 0 if i.blocking else 1)
    return issues


def blocking(issues: list[Issue]) -> list[str]:
    return [issue.detail for issue in issues if issue.blocking]
