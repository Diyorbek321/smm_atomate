"""The parts of a brand that colour cannot carry.

:mod:`app.services.style_dna` pins how a business's photographs look.
:attr:`KnowledgeBase.brand_colors` pins what colour they are. Between them
they solved half of the complaint this system exists to answer — every
client's feed looking the same — and left the other half untouched:

* **Typography** was hardcoded. A language centre and a barbershop shipped
  cards set in identical type, which is the single loudest signal that two
  feeds came out of one machine.
* **Voice** was a six-value enum. `casual` cannot tell a law firm from a
  bakery, and the copy proved it.
* **Banned words** were global. The house list forbids empty marketing filler
  for everyone; it has nothing to say about the one word a particular owner
  refuses to see in their feed.

All three live in one JSONB blob for the reason `visual_style` does: the shape
is still moving and each attribute is not worth a migration. Every field falls
back on its own, so an owner who only pins a font keeps sensible defaults for
the rest.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger

log = get_logger(__name__)

#: Faces the renderers actually ship. A brand may only choose among these —
#: naming a font nobody has installed produces a silent fallback, which looks
#: like a bug and is invisible until a client points at it.
AVAILABLE_FONTS = ("Anton", "Inter", "Manrope", "Unbounded", "JetBrains Mono")

DEFAULT_DISPLAY = "Anton"
DEFAULT_BODY = "Inter"

#: Long enough to steer, short enough not to crowd out the brief.
MAX_RULE = 140
MAX_RULES = 6
MAX_BANNED = 30


class Typography(BaseModel):
    """Which of the shipped faces this brand sets its type in."""

    display: str = DEFAULT_DISPLAY
    body: str = DEFAULT_BODY

    def stack(self, role: str = "body") -> str:
        """A CSS font stack — the chosen face first, then the house fallback."""
        chosen = self.display if role == "display" else self.body
        tail = "'Inter', 'Segoe UI', system-ui, sans-serif"
        return f"'{chosen}', {tail}" if chosen != DEFAULT_BODY else tail


class Voice(BaseModel):
    """How this brand sounds, in a form the copywriter can be told."""

    summary: str = ""
    do: list[str] = Field(default_factory=list)
    dont: list[str] = Field(default_factory=list)
    #: Words this brand refuses, on top of the house list in app/utils/text.py.
    banned_words: list[str] = Field(default_factory=list)

    def prompt_block(self) -> str:
        """The voice as an instruction, or empty when nothing is pinned."""
        parts: list[str] = []
        if self.summary:
            parts.append(f"BREND OVOZI: {self.summary}")
        if self.do:
            parts.append("SHUNDAY YOZ:\n" + "\n".join(f"- {rule}" for rule in self.do))
        if self.dont:
            parts.append("BUNDAY YOZMA:\n" + "\n".join(f"- {rule}" for rule in self.dont))
        if self.banned_words:
            listed = ", ".join(f"«{word}»" for word in self.banned_words)
            parts.append(f"BU BRENDDA TAQIQLANGAN IBORALAR: {listed}")
        return "\n\n".join(parts)


class BrandKit(BaseModel):
    """Everything about a brand that is neither a colour nor a photograph."""

    typography: Typography = Field(default_factory=Typography)
    voice: Voice = Field(default_factory=Voice)
    #: The line a clip signs off with, under the name. Empty is a valid answer
    #: and the honest default — see `app.agents.kinetic.outro_tagline`.
    tagline: str = ""
    #: Which logo file to place on which background. Empty falls back to
    #: `KnowledgeBase.logo_url` for both.
    logo_on_dark: str = ""
    logo_on_light: str = ""

    def logo_for(self, dark_background: bool, fallback: str = "") -> str:
        chosen = self.logo_on_dark if dark_background else self.logo_on_light
        return chosen or fallback


def _clean_rules(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = [str(item).strip()[:MAX_RULE] for item in value if str(item).strip()]
    return cleaned[:MAX_RULES]


def _clean_words(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    words: list[str] = []
    for item in value:
        word = str(item).strip().lower()
        if word and word not in seen:
            seen.add(word)
            words.append(word)
    return words[:MAX_BANNED]


def _typography(stored: dict[str, Any]) -> Typography:
    """Only faces we ship. A name nobody has installed fails silently."""
    raw = stored if isinstance(stored, dict) else {}
    chosen: dict[str, str] = {}
    for role, default in (("display", DEFAULT_DISPLAY), ("body", DEFAULT_BODY)):
        value = str(raw.get(role, "")).strip()
        if value and value not in AVAILABLE_FONTS:
            log.warning("brand_font_unavailable", role=role, font=value[:40])
            value = ""
        chosen[role] = value or default
    return Typography(**chosen)


def kit_for(stored: dict[str, Any] | None) -> BrandKit:
    """The business's kit, with every field falling back on its own."""
    if not stored or not isinstance(stored, dict):
        return BrandKit()

    voice_raw = stored.get("voice")
    voice_raw = voice_raw if isinstance(voice_raw, dict) else {}

    return BrandKit(
        typography=_typography(stored.get("typography") or {}),
        voice=Voice(
            summary=str(voice_raw.get("summary", "")).strip()[:MAX_RULE],
            do=_clean_rules(voice_raw.get("do")),
            dont=_clean_rules(voice_raw.get("dont")),
            banned_words=_clean_words(voice_raw.get("banned_words")),
        ),
        tagline=str(stored.get("tagline") or "").strip()[:MAX_RULE],
        logo_on_dark=str(stored.get("logo_on_dark", "")).strip(),
        logo_on_light=str(stored.get("logo_on_light", "")).strip(),
    )


def find_banned_words(text: str, words: list[str]) -> list[str]:
    """Which of this brand's forbidden words the copy used.

    Whole-word matching, like the banned-topic check: `bot` must not fire
    inside `botanika`. Apostrophe variants are normalised first, because the
    same word arrives spelled three ways depending on the keyboard.
    """
    import re

    from app.utils.text import normalize_apostrophes

    if not words:
        return []
    haystack = normalize_apostrophes(text or "").lower()
    found: list[str] = []
    for word in words:
        needle = normalize_apostrophes(word).lower()
        if re.search(rf"(?<![\w']){re.escape(needle)}(?![\w'])", haystack):
            found.append(word)
    return found
