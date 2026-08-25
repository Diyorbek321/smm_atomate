"""Translating a brandbook file into the fields a machine reads.

The database is derived from the file, so the risky direction is a brandbook
that is silent about something quietly erasing it. These tests pin what the
translation emits — and, just as importantly, what it leaves alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from apply_brandbook import (
    colors_from,
    contacts_from,
    kit_from,
    style_from,
)

BOOK = {
    "name": "Postchi",
    "palette": {
        "bg": "#0F2B63",
        "deep": "#081A3F",
        "ink": "#FFFFFF",
        "brand": "#7FB0FF",
        "accent": "#FFCE1B",
        "muted": "#8CA3C7",
    },
    "typography": {"display": "Anton", "body": "Inter"},
    "voice": {
        "in_one_line": "Muhandis gapiradi",
        "do": ["Raqam bilan gapir"],
        "dont": ["Undov ishlatma"],
        "banned_words": ["inqilobiy"],
    },
    "logo": {"avatar": "mark-yellow.svg", "on_light": "mark-blue.svg"},
    "channels": {"contact": "@inovatex", "instagram": "@postchi.ai"},
    "contact": {"phone": "+998 93 191 33 08"},
    "visual_style": {"palette": "deep navy field", "lighting": "hard directional"},
}


class TestColours:
    def test_design_names_map_to_renderer_names(self):
        colors = colors_from(BOOK)
        assert colors["bg"] == "#0F2B63"
        assert colors["surface"] == "#081A3F"      # brandbook calls it `deep`
        assert colors["text"] == "#FFFFFF"         # brandbook calls it `ink`
        assert colors["primary"] == "#7FB0FF"      # brandbook calls it `brand`

    def test_on_accent_defaults_to_the_field_colour(self):
        """A yellow pill's label is the dark field, and no designer writes it down."""
        assert colors_from(BOOK)["on_accent"] == "#0F2B63"

    def test_an_explicit_on_accent_wins(self):
        book = {"palette": dict(BOOK["palette"], on_accent="#000000")}
        assert colors_from(book)["on_accent"] == "#000000"

    def test_a_colour_that_is_not_a_hex_is_dropped(self):
        book = {"palette": {"bg": "ko'k", "accent": "#FFCE1B"}}
        colors = colors_from(book)
        assert "bg" not in colors
        assert colors["accent"] == "#FFCE1B"

    def test_no_palette_emits_nothing_rather_than_defaults(self):
        """Emitting defaults here would overwrite a brand the file says nothing about."""
        assert colors_from({}) == {}


class TestKit:
    def test_typography_voice_and_logos_are_carried(self):
        kit = kit_from(BOOK, [])
        assert kit["typography"] == {"display": "Anton", "body": "Inter"}
        assert kit["voice"]["summary"] == "Muhandis gapiradi"
        assert kit["voice"]["banned_words"] == ["inqilobiy"]
        assert kit["logo_on_dark"] == "mark-yellow.svg"
        assert kit["logo_on_light"] == "mark-blue.svg"

    def test_an_uninstalled_font_is_skipped_and_reported(self):
        warn: list[str] = []
        kit = kit_from({"typography": {"display": "Helvetica", "body": "Inter"}}, warn)
        assert kit["typography"] == {"body": "Inter"}
        assert warn and "Helvetica" in warn[0]

    def test_an_empty_voice_is_not_emitted(self):
        """An empty voice block would replace a real one with blanks."""
        assert "voice" not in kit_from({"voice": {"do": [], "dont": []}}, [])

    def test_an_empty_book_emits_an_empty_kit(self):
        assert kit_from({}, []) == {}


class TestStyleAndContacts:
    def test_only_the_five_style_clauses_are_taken(self):
        book = {"visual_style": dict(BOOK["visual_style"], note="izoh, prompt uchun emas")}
        style = style_from(book)
        assert style == {"palette": "deep navy field", "lighting": "hard directional"}
        assert "note" not in style

    def test_handles_lose_their_at_sign(self):
        contacts = contacts_from(BOOK)
        assert contacts["telegram_username"] == "inovatex"
        assert contacts["instagram_username"] == "postchi.ai"

    def test_the_phone_is_carried_verbatim(self):
        assert contacts_from(BOOK)["phone"] == "+998 93 191 33 08"

    def test_missing_channels_emit_nothing(self):
        assert contacts_from({}) == {}


class TestWhatItRefusesToTouch:
    def test_the_translation_names_only_brand_fields(self):
        """Prices, offerings and FAQ belong to the knowledge base, not the book."""
        emitted = set(colors_from(BOOK)) | set(kit_from(BOOK, [])) | set(contacts_from(BOOK))
        for owned_elsewhere in ("prices", "key_offerings", "faq", "usps", "raw_notes"):
            assert owned_elsewhere not in emitted
