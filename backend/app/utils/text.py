"""Text helpers: slugs, hashtags, caption hygiene, platform limits."""

from __future__ import annotations

import re
import unicodedata

#: Hard platform limits.
IG_CAPTION_LIMIT = 2200
TG_CAPTION_LIMIT = 1024      # photo caption
TG_MESSAGE_LIMIT = 4096      # plain text message
IG_HASHTAG_LIMIT = 30

_TRANSLIT = {
    "ʻ": "'", "ʼ": "'", "‘": "'", "’": "'", "“": '"', "”": '"',
}

_PLACEHOLDER_RE = re.compile(r"(\[[^\]\n]{2,40}\]|\{\{[^}]{2,40}\}\}|<[A-Z_]{3,30}>|XXX|TODO|LOREM)")
_ROBOTIC_PHRASES = (
    "sun'iy intellekt sifatida",
    "as an ai",
    "men bir ai",
    "quyidagi post",
    "mana sizga post",
    "here is the post",
    "certainly!",
    "albatta! mana",
    "i hope this helps",
)


def normalize_apostrophes(text: str) -> str:
    for src, dst in _TRANSLIT.items():
        text = text.replace(src, dst)
    return text


def slugify(value: str, max_length: int = 60) -> str:
    value = normalize_apostrophes(value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:max_length] or "business"


def normalize_hashtags(tags: list[str] | None, limit: int = IG_HASHTAG_LIMIT) -> list[str]:
    """Deduplicate, prefix with `#`, strip spaces, cap at the platform limit."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in tags or []:
        tag = re.sub(r"\s+", "", str(raw)).strip()
        if not tag:
            continue
        tag = "#" + tag.lstrip("#")
        if len(tag) < 3:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def strip_markdown_fences(text: str) -> str:
    return re.sub(r"^```[a-zA-Z]*\n?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()


def find_placeholders(text: str) -> list[str]:
    """Detect unfilled template slots such as `[narx]` or `{{name}}`."""
    return sorted({m.group(0) for m in _PLACEHOLDER_RE.finditer(text or "")})


def find_robotic_phrases(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [p for p in _ROBOTIC_PHRASES if p in lowered]


def truncate_caption(text: str, limit: int, suffix: str = "…") -> str:
    """Trim to `limit` characters on a word/line boundary when possible."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    window = text[: limit - len(suffix)]
    for sep in ("\n\n", "\n", ". ", " "):
        cut = window.rfind(sep)
        if cut > limit * 0.6:
            return window[:cut].rstrip() + suffix
    return window.rstrip() + suffix


def _flatten(text: str) -> str:
    """Whitespace- and case-insensitive form used for duplicate detection."""
    return re.sub(r"\s+", " ", normalize_apostrophes(text or "")).strip().lower()


def append_block(text: str, block: str) -> str:
    """Append a block (CTA / contacts / hashtags) unless it is already there.

    The model often writes the contacts inline on one line while our block is
    newline-separated, so the comparison ignores whitespace and also accepts a
    per-line match — otherwise every post ends with the phone number twice.
    """
    text = (text or "").rstrip()
    block = (block or "").strip()
    if not block:
        return text

    haystack = _flatten(text)
    if not haystack:
        return block

    if _flatten(block) in haystack:
        return text

    lines = [_flatten(line) for line in block.splitlines() if line.strip()]
    if lines and all(line in haystack for line in lines):
        return text

    return f"{text}\n\n{block}"


#: A phone as people actually type it: +998 93 191-33-08, (93) 1913308, ...
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{6,}\d")


def _digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def dedupe_phone(caption: str, phone: str) -> str:
    """Leave the phone number in the caption exactly once.

    The copywriter writes it into its CTA, the contact block adds it again,
    and the editor's rewrite can reintroduce both — a post printing the same
    number twice reads as careless. The first mention is kept; later ones are
    removed along with any punctuation left dangling.
    """
    target = _digits(phone)[-9:]
    if not caption or len(target) < 7:
        return caption

    seen = False
    kept: list[str] = []
    for line in caption.split("\n"):
        matches = [m for m in _PHONE_RE.finditer(line) if target in _digits(m.group())]
        if not matches:
            kept.append(line)
            continue
        if not seen:
            seen = True
            kept.append(line)
            continue

        stripped = line
        for match in reversed(matches):
            stripped = stripped[: match.start()] + stripped[match.end() :]
        stripped = re.sub(r"\s{2,}", " ", stripped)
        # "Qo'ng'iroq qiling: 🎓" — a colon left pointing at nothing but an
        # emoji reads worse than no colon at all.
        stripped = re.sub(r"[:·—–-]+(?=\s*[^\w]*$)", "", stripped)
        stripped = re.sub(r"\s{2,}", " ", stripped)
        stripped = re.sub(r"[\s:·—–-]+$", "", stripped).strip()
        # A line that was only the number is dropped; one with words survives.
        if stripped and any(ch.isalpha() for ch in stripped):
            kept.append(stripped)

    return "\n".join(kept).strip()


def contains_any(text: str, needles: list[str]) -> bool:
    lowered = (text or "").lower()
    return any(n and n.lower() in lowered for n in needles)


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text or "") if w])


def html_escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
