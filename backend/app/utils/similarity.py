"""How close a new piece of copy is to something this business already posted.

A month of generated content drifts toward its own average: the same hook, the
same headline shape, the same four words. Each post passes every other check —
it is only wrong next to the eleven before it. So the comparison has to happen
against history, not inside one caption.

Jaccard over content words, not characters: `Sentabr guruhiga qabul boshlandi`
and `Sentabr guruhiga qabul ochildi` are the same post, and only a word-level
measure says so.
"""

from __future__ import annotations

import re

from app.utils.text import normalize_apostrophes

#: Words that carry no topic. Kept short on purpose — an over-eager stop list
#: makes two unrelated headlines look identical.
STOPWORDS = frozenset(
    {
        "va", "bilan", "uchun", "ham", "bu", "shu", "har", "bir", "biz", "siz",
        "bizning", "sizning", "o'z", "eng", "juda", "kerak", "mumkin", "yoki",
        "lekin", "ammo", "endi", "hozir", "yana", "faqat", "qanday", "nima",
        "the", "and", "for", "you", "your",
    }
)

#: Above this two texts are the same idea wearing different words.
DUPLICATE_THRESHOLD = 0.6

#: Below this many content words the overlap measure is meaningless — a
#: two-word headline is contained in half the feed by accident.
MIN_TOKENS_FOR_OVERLAP = 3

#: At this much overlap it is not a similar post, it is the same one — worth a
#: rewrite rather than a note on the review card.
NEAR_IDENTICAL_THRESHOLD = 0.75


def tokens(text: str) -> set[str]:
    normalised = normalize_apostrophes(text or "").lower()
    words = re.findall(r"[\w']+", normalised)
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def similarity(left: str, right: str) -> float:
    """How much of the shorter text the longer one already contains, 0.0 – 1.0.

    Plain Jaccard is the obvious choice and it is wrong here. Headlines are
    five words long, so a single different verb — `qabul boshlandi` against
    `qabul ochildi` — costs two tokens out of seven and drags the score under
    any useful threshold, while the two posts are plainly the same post.

    The overlap coefficient asks the question that actually matters: is the
    shorter headline already inside the longer one? Very short strings fall
    back to Jaccard, because two content words match by coincidence.
    """
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if min(len(a), len(b)) < MIN_TOKENS_FOR_OVERLAP:
        return shared / len(a | b)
    return shared / min(len(a), len(b))


def most_similar(text: str, history: list[str]) -> tuple[str, float]:
    """The closest thing already posted, and how close it is.

    Returns `("", 0.0)` when there is no history — a first post cannot repeat
    itself, and callers should not have to special-case that.
    """
    best, score = "", 0.0
    for other in history:
        value = similarity(text, other)
        if value > score:
            best, score = other, value
    return best, score
