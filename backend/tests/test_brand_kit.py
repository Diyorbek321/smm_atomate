"""The brand attributes that are neither colour nor photograph."""

from __future__ import annotations

import pytest

from app.services.brand_kit import (
    AVAILABLE_FONTS,
    DEFAULT_BODY,
    DEFAULT_DISPLAY,
    MAX_BANNED,
    MAX_RULES,
    find_banned_words,
    kit_for,
)


class TestDefaults:
    def test_no_kit_at_all_still_gives_a_usable_one(self):
        """Most businesses will never fill this in, and must still render."""
        kit = kit_for(None)
        assert kit.typography.display == DEFAULT_DISPLAY
        assert kit.typography.body == DEFAULT_BODY
        assert kit.voice.prompt_block() == ""

    @pytest.mark.parametrize("junk", [{}, [], "matn", 0])
    def test_junk_in_the_column_does_not_crash(self, junk):
        assert kit_for(junk).typography.display == DEFAULT_DISPLAY

    def test_one_pinned_field_keeps_defaults_for_the_rest(self):
        kit = kit_for({"typography": {"display": "Unbounded"}})
        assert kit.typography.display == "Unbounded"
        assert kit.typography.body == DEFAULT_BODY


class TestTypography:
    def test_only_shipped_faces_are_accepted(self):
        """A font nobody installed falls silently through to DejaVu."""
        assert kit_for({"typography": {"display": "Helvetica"}}).typography.display == DEFAULT_DISPLAY

    @pytest.mark.parametrize("font", AVAILABLE_FONTS)
    def test_every_advertised_face_is_accepted(self, font: str):
        assert kit_for({"typography": {"body": font}}).typography.body == font

    def test_the_stack_names_the_chosen_face_first(self):
        stack = kit_for({"typography": {"display": "Unbounded"}}).typography.stack("display")
        assert stack.startswith("'Unbounded'")
        assert "system-ui" in stack           # fallback survives


class TestVoice:
    KIT = {
        "voice": {
            "summary": "Muhandis gapiradi",
            "do": ["Raqam bilan gapir"],
            "dont": ["Undov belgisi ishlatma"],
            "banned_words": ["inqilobiy", "zamonaviy yechim"],
        }
    }

    def test_the_block_carries_every_section(self):
        block = kit_for(self.KIT).voice.prompt_block()
        assert "Muhandis gapiradi" in block
        assert "Raqam bilan gapir" in block
        assert "Undov belgisi ishlatma" in block
        assert "inqilobiy" in block

    def test_an_empty_voice_adds_nothing_to_the_prompt(self):
        """Empty sections must not spend tokens on blank headings."""
        assert kit_for({"voice": {}}).voice.prompt_block() == ""

    def test_rules_are_capped_so_they_cannot_crowd_out_the_brief(self):
        many = {"voice": {"do": [f"qoida {i}" for i in range(30)]}}
        assert len(kit_for(many).voice.do) == MAX_RULES

    def test_banned_words_are_capped_and_deduplicated(self):
        raw = {"voice": {"banned_words": ["Bir", "bir", "BIR"] + [f"w{i}" for i in range(50)]}}
        words = kit_for(raw).voice.banned_words
        assert len(words) <= MAX_BANNED
        assert words.count("bir") == 1


class TestBannedWordMatching:
    WORDS = ["inqilobiy", "zamonaviy yechim"]

    def test_a_forbidden_word_is_found(self):
        assert find_banned_words("Bu inqilobiy platforma", self.WORDS) == ["inqilobiy"]

    def test_a_multi_word_phrase_is_found(self):
        assert "zamonaviy yechim" in find_banned_words("Bizning zamonaviy yechim", self.WORDS)

    def test_it_does_not_fire_inside_a_longer_word(self):
        """`bot` must not match inside `botanika` — same rule as banned topics."""
        assert find_banned_words("inqilobiylik tarixi", self.WORDS) == []

    def test_apostrophe_variants_are_the_same_word(self):
        for apostrophe in ("'", "‘", "’", "ʻ"):
            assert find_banned_words(f"sun{apostrophe}iy kuch", ["sun'iy kuch"])

    def test_no_words_means_no_work(self):
        assert find_banned_words("istalgan matn", []) == []


class TestLogoVariants:
    def test_the_dark_variant_is_used_on_a_dark_background(self):
        kit = kit_for({"logo_on_dark": "a.svg", "logo_on_light": "b.svg"})
        assert kit.logo_for(dark_background=True) == "a.svg"
        assert kit.logo_for(dark_background=False) == "b.svg"

    def test_it_falls_back_to_the_single_logo(self):
        assert kit_for({}).logo_for(dark_background=True, fallback="logo.png") == "logo.png"
