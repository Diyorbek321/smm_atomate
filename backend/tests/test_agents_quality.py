"""The quality-loop machinery's deterministic halves.

Learned-rule resolution, feedback digestion, rule clamping, gold-example
rendering and the rewrite budget are all plain code around LLM calls — the
part that must hold without a provider, so the part covered here.
"""

from __future__ import annotations

import uuid

from app.agents.base import LEARNED_PREFIX, resolve_prompt
from app.agents.copywriter import (
    GOLD_EXAMPLES_MAX,
    MAX_OUTPUT_TOKENS,
    CopywriterAgent,
    token_budget,
)
from app.agents.editor import EditorResult
from app.agents.orchestrator import (
    MAX_REWRITES,
    REWRITE_THRESHOLD,
    SECOND_REWRITE_BELOW,
    _should_rewrite,
)
from app.agents.prompts import MAX_LEARNED_RULES
from app.agents.style_distiller import (
    DistilledRules,
    StyleDistillerAgent,
    feedback_digest,
    render_rules_block,
)
from app.models.content_item import SUPERSEDED_NOTE, ContentItem
from app.models.enums import ContentItemStatus, ContentPillar, ContentType
from app.models.prompt_template import PromptTemplate
from app.schemas.content import CopyOutput, EditorOutput

BUSINESS = uuid.uuid4()
OTHER = uuid.uuid4()


def template(
    name: str = "custom",
    *,
    business_id: uuid.UUID | None = None,
    pillar: ContentPillar | None = None,
    prompt: str = "OVERRIDE",
) -> PromptTemplate:
    return PromptTemplate(
        business_id=business_id, name=name, agent="copywriter", pillar=pillar, system_prompt=prompt
    )


# --------------------------------------------------------------------------- #
# Prompt resolution with learned addenda
# --------------------------------------------------------------------------- #
class TestResolvePrompt:
    def test_no_rows_returns_default(self):
        prompt, used = resolve_prompt([], "DEFAULT", business_id=BUSINESS, pillar=None)
        assert prompt == "DEFAULT"
        assert used == []

    def test_business_override_replaces_default(self):
        rows = [template(business_id=BUSINESS, prompt="BIZNESNIKI")]
        prompt, used = resolve_prompt(rows, "DEFAULT", business_id=BUSINESS, pillar=None)
        assert prompt == "BIZNESNIKI"
        assert used == rows

    def test_business_pillar_override_beats_business_wide(self):
        wide = template("wide", business_id=BUSINESS, prompt="KENG")
        scoped = template(
            "scoped", business_id=BUSINESS, pillar=ContentPillar.SALES, prompt="SOTUV"
        )
        prompt, _ = resolve_prompt(
            [wide, scoped], "DEFAULT", business_id=BUSINESS, pillar=ContentPillar.SALES
        )
        assert prompt == "SOTUV"

    def test_learned_addendum_appends_to_default(self):
        rows = [template(LEARNED_PREFIX + "copywriter", business_id=BUSINESS, prompt="- qoida")]
        prompt, used = resolve_prompt(rows, "DEFAULT", business_id=BUSINESS, pillar=None)
        assert prompt == "DEFAULT\n\n- qoida"
        assert used == rows

    def test_learned_addendum_appends_to_override_too(self):
        """A hand-tuned override must not silently discard the learned rules."""
        rows = [
            template(business_id=BUSINESS, prompt="BIZNESNIKI"),
            template(LEARNED_PREFIX + "copywriter", business_id=BUSINESS, prompt="- qoida"),
        ]
        prompt, used = resolve_prompt(rows, "DEFAULT", business_id=BUSINESS, pillar=None)
        assert prompt == "BIZNESNIKI\n\n- qoida"
        assert len(used) == 2

    def test_learned_row_never_replaces_the_base_prompt(self):
        """An addendum alone must leave the default fully intact, not become it."""
        rows = [template(LEARNED_PREFIX + "copywriter", business_id=BUSINESS, prompt="- qoida")]
        prompt, _ = resolve_prompt(rows, "DEFAULT", business_id=BUSINESS, pillar=None)
        assert prompt.startswith("DEFAULT")

    def test_other_businesses_lessons_are_ignored(self):
        rows = [template(LEARNED_PREFIX + "copywriter", business_id=OTHER, prompt="- begona")]
        prompt, used = resolve_prompt(rows, "DEFAULT", business_id=BUSINESS, pillar=None)
        assert prompt == "DEFAULT"
        assert used == []

    def test_blank_addendum_is_not_appended(self):
        rows = [template(LEARNED_PREFIX + "copywriter", business_id=BUSINESS, prompt="   ")]
        prompt, used = resolve_prompt(rows, "DEFAULT", business_id=BUSINESS, pillar=None)
        assert prompt == "DEFAULT"
        assert used == []


# --------------------------------------------------------------------------- #
# Feedback digest
# --------------------------------------------------------------------------- #
def item(
    status: ContentItemStatus = ContentItemStatus.PUBLISHED,
    *,
    notes: str = "",
    topic: str = "IELTS narxi",
    issues: list[dict] | None = None,
) -> ContentItem:
    return ContentItem(
        status=status,
        review_notes=notes,
        topic=topic,
        editor_report={"issues": issues} if issues is not None else {},
    )


class TestFeedbackDigest:
    def test_owner_rejection_with_note_is_a_signal(self):
        digest = feedback_digest([item(ContentItemStatus.REJECTED, notes="narx eskirgan")])
        assert digest["rejections"] == [{"mavzu": "IELTS narxi", "izoh": "narx eskirgan"}]
        assert digest["signals"] == 1

    def test_superseded_rejection_is_not_feedback(self):
        """Plan regeneration rejects drafts wholesale; nobody disliked them."""
        digest = feedback_digest([item(ContentItemStatus.REJECTED, notes=SUPERSEDED_NOTE)])
        assert digest["rejections"] == []
        assert digest["signals"] == 0

    def test_noteless_rejection_is_not_feedback(self):
        digest = feedback_digest([item(ContentItemStatus.REJECTED)])
        assert digest["rejections"] == []

    def test_editor_issue_needs_repetition(self):
        once = [item(issues=[{"severity": "major", "problem": "Aloqa ma'lumoti yo'q"}])]
        assert feedback_digest(once)["repeated_issues"] == {}

        twice = [*once, item(issues=[{"severity": "major", "problem": "Aloqa ma'lumoti yo'q"}])]
        digest = feedback_digest(twice)
        assert digest["repeated_issues"] == {"Aloqa ma'lumoti yo'q": 2}
        assert digest["signals"] == 2

    def test_minor_issues_never_become_rules(self):
        rows = [
            item(issues=[{"severity": "minor", "problem": "Bo'sh ibora"}]),
            item(issues=[{"severity": "minor", "problem": "Bo'sh ibora"}]),
        ]
        assert feedback_digest(rows)["repeated_issues"] == {}

    def test_empty_production_is_zero_signals(self):
        assert feedback_digest([])["signals"] == 0


# --------------------------------------------------------------------------- #
# Distilled-rule clamping and rendering
# --------------------------------------------------------------------------- #
class TestRuleClamp:
    def test_dedupes_and_strips_bullets(self):
        raw = DistilledRules(rules=["- Narxni yozma ", "narxni yozma", "Boshqa qoida"])
        clamped = StyleDistillerAgent._clamp(raw)
        assert clamped.rules == ["Narxni yozma", "Boshqa qoida"]

    def test_caps_the_rule_count(self):
        raw = DistilledRules(rules=[f"Qoida {i}" for i in range(20)])
        assert len(StyleDistillerAgent._clamp(raw).rules) == MAX_LEARNED_RULES

    def test_drops_essays_masquerading_as_rules(self):
        raw = DistilledRules(rules=["x" * 500, "Qisqa qoida"])
        assert StyleDistillerAgent._clamp(raw).rules == ["Qisqa qoida"]

    def test_render_block_is_empty_without_rules(self):
        assert render_rules_block([]) == ""

    def test_render_block_lists_every_rule(self):
        block = render_rules_block(["Birinchi", "Ikkinchi"])
        assert "- Birinchi" in block and "- Ikkinchi" in block
        assert block.startswith("SHU BIZNESDA O'RGANILGAN QOIDALAR")


# --------------------------------------------------------------------------- #
# Gold examples
# --------------------------------------------------------------------------- #
class TestGoldBlock:
    def test_empty_examples_render_nothing(self):
        assert CopywriterAgent._gold_block([]) == ""
        assert CopywriterAgent._gold_block(["   "]) == ""

    def test_caps_count_and_length(self):
        block = CopywriterAgent._gold_block(["uzun " * 200] * 5)
        shown = sum(f"NAMUNA {i}:" in block for i in range(1, 7))
        assert shown == GOLD_EXAMPLES_MAX
        assert len(block) < (GOLD_EXAMPLES_MAX + 1) * 600

    def test_collapses_whitespace_and_numbers_examples(self):
        block = CopywriterAgent._gold_block(["Birinchi\n\npost", "Ikkinchi post"])
        assert "NAMUNA 1:\nBirinchi post" in block
        assert "NAMUNA 2:\nIkkinchi post" in block

    def test_forbids_copying_in_the_header(self):
        assert "KO'CHIRMA" in CopywriterAgent._gold_block(["Post matni"])


class TestTokenBudget:
    def test_long_formats_get_more_room(self):
        """A reels script died mid-JSON at the flat 2500 budget."""
        assert token_budget(ContentType.REELS_SCRIPT) > MAX_OUTPUT_TOKENS
        assert token_budget(ContentType.CAROUSEL) > MAX_OUTPUT_TOKENS

    def test_short_formats_keep_the_default(self):
        assert token_budget(ContentType.FEED_POST) == MAX_OUTPUT_TOKENS
        assert token_budget(ContentType.TELEGRAM_QUIZ) == MAX_OUTPUT_TOKENS


# --------------------------------------------------------------------------- #
# Rewrite budget
# --------------------------------------------------------------------------- #
def review(score: float, approved: bool = False) -> EditorResult:
    return EditorResult(copy=CopyOutput(), report=EditorOutput(approved=approved, score=score))


class TestShouldRewrite:
    def test_good_copy_is_left_alone(self):
        assert not _should_rewrite(review(REWRITE_THRESHOLD, approved=True), 0)

    def test_unapproved_copy_gets_a_first_rewrite(self):
        assert _should_rewrite(review(6.8), 0)

    def test_borderline_copy_gets_no_second_rewrite(self):
        """6.0-6.9 after one rewrite is the review queue's call, not another $0.02."""
        assert not _should_rewrite(review(SECOND_REWRITE_BELOW), 1)

    def test_bad_copy_gets_a_second_rewrite(self):
        assert _should_rewrite(review(SECOND_REWRITE_BELOW - 1.5), 1)

    def test_budget_is_hard_capped(self):
        assert not _should_rewrite(review(1.0), MAX_REWRITES)
