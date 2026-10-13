"""Uzbek Latin rewritten into an orthography a TTS model reads correctly.

The models pronounce Uzbek Latin through English phonetics, and the letters
that carry the most meaning — `q`, `o'`, `g'`, `x` — are exactly the ones that
break. Spelling the same words the way a related language spells them makes the
model reach for a phonology that fits: Turkish is a Turkic language with vowel
harmony, and the output still sounds Uzbek.

Measured on the lab corpus: character error rate 29.9% → 23.8%, against a human
reader's 28.8% on the same passages. Cyrillic was tried too and made it worse.

Only the model ever sees this. The text on screen is untouched.
"""

from __future__ import annotations

import re

#: Every apostrophe a keyboard, a phone or a paste from Word might produce.
APOS = "['’ʻ‘ʼ´`]"

#: Longest sequences first: rewriting `s` before `sh` turns "shu" into "şh".
TURK: tuple[tuple[str, str], ...] = (
    (rf"o{APOS}", "o"), (rf"O{APOS}", "O"),
    (rf"g{APOS}", "ğ"), (rf"G{APOS}", "Ğ"),
    ("sh", "ş"), ("Sh", "Ş"), ("SH", "Ş"),
    ("ch", "ç"), ("Ch", "Ç"), ("CH", "Ç"),
    ("x", "h"), ("X", "H"),
    ("q", "k"), ("Q", "K"),
    ("j", "c"), ("J", "C"),
)

MODES = ("turk", "lotin")


def convert(text: str, mode: str = "turk") -> str:
    """Rewrite for the synthesiser. `lotin` (or anything unknown) is a no-op."""
    if mode != "turk":
        return text
    out = text
    for pattern, replacement in TURK:
        out = (re.sub(pattern, replacement, out) if APOS in pattern
               else out.replace(pattern, replacement))
    return out
