"""Turning a quality verdict into the next render attempt.

:mod:`app.services.visual_qc` decides whether a card is publishable. It has
always been good at that. What followed was not: the retry shortened the
headline, every time, whatever the complaint had been — because the attempts
were built before the first render, so nothing in them could depend on what the
reviewer said.

That is fine for the common case and useless for the rest. A card broken by a
font drawing its glyphs on top of one another was handed "fewer words", twice,
and shipped broken anyway — two renders and two model calls spent pulling a
lever that could not move the defect.

So the verdict picks the lever here. Each lever is pulled at most once: a repair
that has already failed is not worth a second render, and running out of levers
is a real answer — the caller ships the best attempt and tells the owner what
was wrong with it.

Deliberately LLM-free. The reviewer has already done the judging; this is
arithmetic on its answer.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.utils.text import normalize_apostrophes, truncate_caption

log = get_logger(__name__)

#: The four things the reviewer is asked to check, in the order they are worth
#: acting on: a clipped headline ruins the card, an unbalanced margin does not.
CLIPPED = "clipped"
CONTRAST = "contrast"
ARTEFACT = "artefact"
LAYOUT = "layout"

#: Below this the headline stops out-ranking the body and the card reads as a
#: mistake rather than a design.
MIN_TITLE_SIZE = 48
#: How much smaller each shrink goes. Enough to matter in one step — a 5%
#: nudge just buys another render at the same verdict.
SHRINK = 0.82
#: Headline length once shrinking alone has not been enough.
TIGHT_TITLE = 46

_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        CLIPPED,
        ("kesil", "chiqib ketgan", "chegaradan", "sig'ma", "sigma", "to'liq emas",
         "toliq emas", "ustma-ust", "qirqil", "yarim"),
    ),
    (CONTRAST, ("kontrast", "o'qib bo'lmaydi", "oqib bolmaydi", "ko'rinmay", "korinmay",
                "qo'shilib ketgan", "qoshilib ketgan", "xira")),
    (ARTEFACT, ("buzuq", "g'alati", "galati", "ma'nosiz", "manosiz", "barmoq", "yuz",
                "cho'zilgan", "chozilgan", "artefakt")),
)


def diagnose(verdict: Any) -> str:
    """Which of the four defects the reviewer is describing.

    The two booleans come first: they are the reviewer's own structured answer,
    where `issues` is free prose that has to be read for keywords.
    """
    if getattr(verdict, "text_complete", True) is False:
        return CLIPPED
    if getattr(verdict, "readable", True) is False:
        return CONTRAST

    haystack = normalize_apostrophes(" ".join(getattr(verdict, "issues", []) or [])).lower()
    for defect, markers in _MARKERS:
        if any(marker in haystack for marker in markers):
            return defect
    # Something is wrong and the words do not say what. Dropping the supporting
    # line is the cheapest change that alters the composition at all.
    return LAYOUT


def _shrunk(context: dict, factor: float = SHRINK) -> dict | None:
    layout = dict(context.get("layout") or {})
    current = int(layout.get("title_size") or 0)
    target = int(current * factor)
    if not current or target < MIN_TITLE_SIZE:
        return None
    layout["title_size"] = target
    return {**context, "layout": layout}


def _tightened(context: dict) -> dict | None:
    title = str(context.get("title") or "")
    if len(title) <= TIGHT_TITLE:
        return None
    return {**context, "title": truncate_caption(title, TIGHT_TITLE), "body": ""}


def _without_photo(context: dict) -> dict | None:
    if not context.get("photo"):
        return None
    return {**context, "photo": ""}


def _without_body(context: dict) -> dict | None:
    if not str(context.get("body") or "").strip():
        return None
    return {**context, "body": ""}


def repair(context: dict, verdict: Any, tried: set[str]) -> dict | None:
    """The next attempt, or None when every lever for this defect is spent.

    `tried` carries the defects already acted on, so a second clipping verdict
    escalates from "smaller type" to "fewer words" instead of shrinking again.
    """
    defect = diagnose(verdict)

    if defect == CLIPPED:
        # Shrinking first: it keeps the copy the editor approved. Only when the
        # type cannot go smaller does the headline lose words.
        fixed = None if CLIPPED in tried else _shrunk(context)
        if fixed is None:
            fixed = _tightened(context)
    elif defect in (CONTRAST, ARTEFACT):
        # Both come down to the photo. The drawn canvas underneath has a scrim
        # this system controls; a photograph has whatever it has.
        fixed = None if defect in tried else _without_photo(context)
    else:
        fixed = None if LAYOUT in tried else _without_body(context)

    if fixed is None:
        log.info("visual_repair_exhausted", defect=defect, tried=sorted(tried))
        return None

    tried.add(defect)
    log.info("visual_repair", defect=defect, score=getattr(verdict, "score", None))
    return fixed
