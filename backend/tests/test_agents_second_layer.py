"""The second-layer agents' deterministic halves.

Every one of these agents wraps an LLM call in code that clamps whatever comes
back into something the rest of the pipeline can use. The call is not testable
without a provider; the clamping is exactly where the bugs live, so that is
what this covers.
"""

from __future__ import annotations

from app.agents.analyst import AnalysisRequest, AnalysisReport, AnalystAgent, production_stats
from app.agents.designer import DesignBrief, DesignerAgent, DesignRequest
from app.agents.hook import HookAgent, HookOptions
from app.agents.marketolog import MarketingBrief
from app.agents.orchestrator import _replace_opening
from app.agents.researcher import (
    ResearchedFact,
    ResearcherAgent,
    ResearchFindings,
    merge_into_knowledge,
)
from app.agents.video_editor import EditPlan, KeepSegment, VideoEditorAgent
from app.models.content_item import ContentItem
from app.models.enums import ContentItemStatus, ContentPillar, ContentType

from tests.test_agents import make_business, make_knowledge


# --------------------------------------------------------------------------- #
# Hook
# --------------------------------------------------------------------------- #
class TestHookPick:
    def test_takes_the_models_choice(self):
        options = HookOptions(variants=["Birinchi", "Ikkinchi", "Uchinchi"], best_index=1)
        assert HookAgent._pick(options, "eski") == "Ikkinchi"

    def test_out_of_range_index_falls_back_to_first_usable(self):
        """Small models routinely return an index past the end of the list."""
        options = HookOptions(variants=["Birinchi", "Ikkinchi"], best_index=7)
        assert HookAgent._pick(options, "eski") == "Birinchi"

    def test_overlong_pick_is_rejected_for_a_shorter_variant(self):
        long_one = "x" * 200
        options = HookOptions(variants=[long_one, "Qisqa hook"], best_index=0)
        assert HookAgent._pick(options, "eski") == "Qisqa hook"

    def test_all_overlong_keeps_the_original(self):
        options = HookOptions(variants=["x" * 200, "y" * 150], best_index=0)
        assert HookAgent._pick(options, "eski hook") == "eski hook"

    def test_no_variants_keeps_the_original(self):
        assert HookAgent._pick(HookOptions(), "eski hook") == "eski hook"


class TestReplaceOpening:
    def test_swaps_the_first_line_when_it_is_the_hook(self):
        caption = "Eski hook\n\nQolgan matn."
        assert _replace_opening(caption, "Eski hook", "Yangi hook") == "Yangi hook\n\nQolgan matn."

    def test_leaves_caption_alone_when_first_line_is_not_the_hook(self):
        """The hook field still changes; the approved caption must not."""
        caption = "Butunlay boshqa boshlanish\n\nQolgan matn."
        assert _replace_opening(caption, "Eski hook", "Yangi hook") == caption

    def test_matches_past_punctuation_and_case(self):
        caption = "ESKI HOOK!\n\nQolgan."
        assert _replace_opening(caption, "eski hook", "Yangi") == "Yangi\n\nQolgan."

    def test_single_line_caption(self):
        assert _replace_opening("Eski hook", "Eski hook", "Yangi hook") == "Yangi hook"

    def test_empty_inputs_are_noops(self):
        assert _replace_opening("", "a", "b") == ""
        assert _replace_opening("matn", "", "b") == "matn"
        assert _replace_opening("matn", "a", "") == "matn"


# --------------------------------------------------------------------------- #
# Designer
# --------------------------------------------------------------------------- #
def design_request(**overrides) -> DesignRequest:
    base = {
        "business": make_business(),
        "knowledge": make_knowledge(),
        "content_type": ContentType.FEED_POST,
        "pillar": ContentPillar.SALES,
        "topic": "IELTS intensiv",
        "headline": "Qisqa sarlavha",
    }
    base.update(overrides)
    return DesignRequest(**base)


class TestDesignerSanitise:
    def test_unknown_layout_falls_back_to_statement(self):
        brief = DesignBrief(layout="cinematic-collage", focal="Qisqa")
        assert DesignerAgent._sanitise(brief, design_request()).layout == "statement"

    def test_long_focal_forces_split_over_statement(self):
        """A 60+ character line overflows the single-statement card."""
        brief = DesignBrief(layout="statement", focal="j" * 80)
        assert DesignerAgent._sanitise(brief, design_request()).layout == "split"

    def test_empty_focal_falls_back_to_the_headline(self):
        brief = DesignBrief(layout="statement", focal="")
        out = DesignerAgent._sanitise(brief, design_request(headline="Sarlavha bor"))
        assert out.focal == "Sarlavha bor"

    def test_unknown_accent_target_becomes_focal(self):
        brief = DesignBrief(layout="number", focal="600 000", accent_on="background")
        assert DesignerAgent._sanitise(brief, design_request()).accent_on == "focal"

    def test_list_layout_defaults_to_packed_density(self):
        brief = DesignBrief(layout="list", focal="Uch sabab", density="???")
        assert DesignerAgent._sanitise(brief, design_request()).density == "packed"

    def test_valid_brief_survives_untouched(self):
        brief = DesignBrief(
            layout="number", focal="600 000 so'm", accent_on="focal", density="sparse", photo_needed=False
        )
        out = DesignerAgent._sanitise(brief, design_request())
        assert (out.layout, out.accent_on, out.density, out.photo_needed) == (
            "number", "focal", "sparse", False,
        )


# --------------------------------------------------------------------------- #
# Video editor
# --------------------------------------------------------------------------- #
class TestEditPlanSanitise:
    def test_clamps_segments_past_the_end_of_the_file(self):
        plan = EditPlan(keep=[KeepSegment(start=0, end=90)])
        out = VideoEditorAgent._sanitise(plan, duration=30.0)
        assert out.keep[0].end == 30.0

    def test_drops_segments_shorter_than_a_frame(self):
        plan = EditPlan(keep=[KeepSegment(start=1.0, end=1.1), KeepSegment(start=2.0, end=8.0)])
        out = VideoEditorAgent._sanitise(plan, duration=30.0)
        assert [(s.start, s.end) for s in out.keep] == [(2.0, 8.0)]

    def test_overlapping_segments_do_not_duplicate_speech(self):
        plan = EditPlan(keep=[KeepSegment(start=0, end=10), KeepSegment(start=5, end=15)])
        out = VideoEditorAgent._sanitise(plan, duration=30.0)
        assert [(s.start, s.end) for s in out.keep] == [(0.0, 10.0), (10.0, 15.0)]

    def test_segments_are_sorted_before_stitching(self):
        plan = EditPlan(keep=[KeepSegment(start=20, end=25), KeepSegment(start=2, end=8)])
        out = VideoEditorAgent._sanitise(plan, duration=30.0)
        assert [s.start for s in out.keep] == [2.0, 20.0]

    def test_total_is_trimmed_to_the_publishable_ceiling(self):
        plan = EditPlan(keep=[KeepSegment(start=0, end=40), KeepSegment(start=40, end=100)])
        out = VideoEditorAgent._sanitise(plan, duration=120.0)
        assert out.total_seconds <= 60.0

    def test_hook_outside_the_file_is_dropped(self):
        plan = EditPlan(keep=[KeepSegment(start=0, end=10)], hook_at=95.0)
        assert VideoEditorAgent._sanitise(plan, duration=30.0).hook_at is None

    def test_unknown_subtitle_style_becomes_full(self):
        plan = EditPlan(keep=[KeepSegment(start=0, end=10)], subtitle_style="karaoke")
        assert VideoEditorAgent._sanitise(plan, duration=30.0).subtitle_style == "full"

    def test_empty_plan_is_not_usable(self):
        assert EditPlan(keep=[]).is_usable is False

    def test_transcript_block_skips_unparseable_rows(self):
        block = VideoEditorAgent._transcript_block(
            [
                {"start": 0.0, "end": 2.0, "text": "Salom"},
                {"start": "yomon", "end": 4.0, "text": "Tushmaydi"},
                {"start": 4.0, "end": 6.0, "text": "   "},
            ]
        )
        assert block == "[0.0-2.0] Salom"


# --------------------------------------------------------------------------- #
# Researcher
# --------------------------------------------------------------------------- #
class TestResearcherSanitise:
    def test_facts_without_a_number_are_not_checkable(self):
        findings = ResearchFindings(
            facts=[ResearchedFact(label="Sifat", value="juda yaxshi", confidence=0.9)]
        )
        assert ResearcherAgent._sanitise(findings, []).facts == []

    def test_duplicates_within_one_run_are_collapsed(self):
        fact = ResearchedFact(label="IELTS narxi", value="600000 so'm", confidence=0.9)
        findings = ResearchFindings(facts=[fact, fact.model_copy()])
        assert len(ResearcherAgent._sanitise(findings, []).facts) == 1

    def test_already_known_facts_are_dropped(self):
        findings = ResearchFindings(
            facts=[ResearchedFact(label="IELTS narxi", value="600000 so'm", confidence=0.9)]
        )
        out = ResearcherAgent._sanitise(findings, ["IELTS narxi — 600000 so'm"])
        assert out.facts == []

    def test_questions_are_capped(self):
        findings = ResearchFindings(questions=[f"Savol {i}?" for i in range(12)])
        assert len(ResearcherAgent._sanitise(findings, []).questions) == 5

    def test_low_confidence_facts_are_kept_but_not_trusted(self):
        findings = ResearchFindings(
            facts=[ResearchedFact(label="Guruh", value="12 kishi", confidence=0.3)]
        )
        clean = ResearcherAgent._sanitise(findings, [])
        assert len(clean.facts) == 1
        assert clean.trusted() == []


class TestMergeIntoKnowledge:
    def test_appends_under_a_heading_and_leaves_notes_intact(self):
        knowledge = make_knowledge(raw_notes="Ega yozgan eslatma.")
        findings = ResearchFindings(
            facts=[ResearchedFact(label="Guruh hajmi", value="12 kishi", confidence=0.9)]
        )
        report = merge_into_knowledge(knowledge, findings)

        assert report["added"] == 1
        assert "Ega yozgan eslatma." in knowledge.raw_notes
        assert "TADQIQOT FAKTLARI:" in knowledge.raw_notes
        assert "Guruh hajmi — 12 kishi" in knowledge.raw_notes

    def test_second_run_does_not_duplicate_the_same_fact(self):
        knowledge = make_knowledge(raw_notes="")
        findings = ResearchFindings(
            facts=[ResearchedFact(label="Guruh hajmi", value="12 kishi", confidence=0.9)]
        )
        merge_into_knowledge(knowledge, findings)
        second = merge_into_knowledge(knowledge, findings)

        assert second["added"] == 0
        assert knowledge.raw_notes.count("Guruh hajmi") == 1

    def test_structured_fields_are_never_touched(self):
        """A research run must not be able to rewrite a price the owner set."""
        knowledge = make_knowledge()
        before = list(knowledge.prices)
        merge_into_knowledge(
            knowledge,
            ResearchFindings(
                facts=[ResearchedFact(label="IELTS narxi", value="999999 so'm", confidence=1.0)]
            ),
        )
        assert knowledge.prices == before

    def test_untrusted_facts_are_not_written(self):
        knowledge = make_knowledge(raw_notes="")
        merge_into_knowledge(
            knowledge,
            ResearchFindings(
                facts=[ResearchedFact(label="Guruh", value="12 kishi", confidence=0.2)]
            ),
        )
        assert "Guruh" not in knowledge.raw_notes


# --------------------------------------------------------------------------- #
# Marketolog
# --------------------------------------------------------------------------- #
class TestMarketingBrief:
    def test_empty_brief_is_not_usable(self):
        assert MarketingBrief().is_usable is False
        assert MarketingBrief().as_instructions() == ""

    def test_blank_fields_are_omitted_rather_than_sent_as_empty_labels(self):
        brief = MarketingBrief(segment="25-35 yosh ota-onalar", offer="", angle="")
        rendered = brief.as_instructions()
        assert "SEGMENT" in rendered
        assert "TAKLIF" not in rendered

    def test_avoid_list_is_rendered(self):
        brief = MarketingBrief(segment="X", avoid=["chegirma", "bayram"])
        assert "TEGMA: chegirma, bayram" in brief.as_instructions()


# --------------------------------------------------------------------------- #
# Analyst
# --------------------------------------------------------------------------- #
def make_item(**overrides) -> ContentItem:
    item = ContentItem(
        content_type=ContentType.FEED_POST,
        pillar=ContentPillar.SALES,
        status=ContentItemStatus.PUBLISHED,
        topic="Mavzu",
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


class TestProductionStats:
    def test_no_items_reports_zero(self):
        assert production_stats([]) == {"total": 0}

    def test_counts_by_pillar_and_status(self):
        stats = production_stats(
            [
                make_item(pillar=ContentPillar.SALES),
                make_item(pillar=ContentPillar.EDUCATIONAL),
                make_item(pillar=ContentPillar.SALES, status=ContentItemStatus.REJECTED),
            ]
        )
        assert stats["total"] == 3
        assert stats["by_pillar"]["sales"] == 2
        assert stats["rejected"] == 1

    def test_quality_average_ignores_unscored_items(self):
        stats = production_stats(
            [make_item(quality_score=8.0), make_item(quality_score=6.0), make_item(quality_score=0.0)]
        )
        assert stats["avg_quality"] == 7.0
        assert stats["measured_quality"] == 2
        assert stats["low_quality"] == 1


class TestAnalystConfidence:
    def _request(self, total: int, measured: int) -> AnalysisRequest:
        return AnalysisRequest(
            business=make_business(),
            production={"total": total},
            performance={"by_pillar": {"sales": {"posts": total, "measured": measured}}},
        )

    def test_small_sample_caps_a_confident_report(self):
        report = AnalysisReport(confidence=0.95, recommendations=["Ko'proq sales post"])
        capped = AnalystAgent._cap_confidence(report, self._request(total=3, measured=3))
        assert capped.confidence <= 0.4
        assert capped.note

    def test_unmeasured_reactions_cap_confidence(self):
        report = AnalysisReport(confidence=0.9)
        capped = AnalystAgent._cap_confidence(report, self._request(total=40, measured=1))
        assert capped.confidence <= 0.5

    def test_large_measured_sample_keeps_the_models_confidence(self):
        report = AnalysisReport(confidence=0.8)
        capped = AnalystAgent._cap_confidence(report, self._request(total=40, measured=30))
        assert capped.confidence == 0.8

    def test_findings_and_recommendations_are_capped(self):
        report = AnalysisReport(
            confidence=0.8,
            findings=[{"text": f"f{i}", "evidence": ""} for i in range(9)],
            recommendations=[f"r{i}" for i in range(9)],
        )
        capped = AnalystAgent._cap_confidence(report, self._request(total=40, measured=30))
        assert len(capped.findings) == 4
        assert len(capped.recommendations) == 3

    def test_reaction_block_warns_when_nothing_was_measured(self):
        block = AnalystAgent._reaction_block(
            {"published": 12, "by_pillar": {"sales": {"posts": 12, "measured": 0}}}
        )
        assert "CHIQARMA" in block


# --------------------------------------------------------------------------- #
# Prompt blocks and the paths that answer before any LLM call
# --------------------------------------------------------------------------- #
class TestPerformanceBlock:
    def test_no_history_says_so_plainly(self):
        from app.agents.marketolog import MarketologAgent

        block = MarketologAgent._performance_block({})
        assert "hali e'lon qilingan post yo'q" in block

    def test_measured_pillar_reports_posts_and_average_together(self):
        from app.agents.marketolog import MarketologAgent

        block = MarketologAgent._performance_block(
            {
                "published": 9,
                "by_pillar": {"sales": {"posts": 5, "measured": 4, "avg_reactions": 2.5}},
                "recent_topics": ["IELTS", "Speaking"],
            }
        )
        assert "5 post" in block and "4 tasi o'lchangan" in block and "2.5" in block

    def test_unmeasured_pillar_is_labelled_not_averaged(self):
        from app.agents.marketolog import MarketologAgent

        block = MarketologAgent._performance_block(
            {"published": 3, "by_pillar": {"sales": {"posts": 3, "measured": 0, "avg_reactions": None}}}
        )
        assert "reaksiya o'lchanmagan" in block

    def test_recent_topics_are_listed_so_they_are_not_repeated(self):
        from app.agents.marketolog import MarketologAgent

        block = MarketologAgent._performance_block(
            {"published": 2, "by_pillar": {}, "recent_topics": ["IELTS intensiv"]}
        )
        assert "IELTS intensiv" in block


class TestResearcherKnownBlock:
    def test_empty_when_nothing_is_known(self):
        assert ResearcherAgent._known_block([]) == ""

    def test_lists_known_facts_so_they_are_not_returned_again(self):
        block = ResearcherAgent._known_block(["IELTS narxi — 600000"])
        assert "ALLAQACHON MA'LUM" in block and "600000" in block


class TestAnalystReactionBlock:
    def test_nothing_published_yet(self):
        assert "e'lon qilingan post yo'q" in AnalystAgent._reaction_block({})

    def test_measured_pillars_are_listed(self):
        block = AnalystAgent._reaction_block(
            {
                "published": 10,
                "by_pillar": {"sales": {"posts": 6, "measured": 5, "avg_reactions": 2.1}},
            }
        )
        assert "sales" in block and "2.1" in block


class TestEarlyReturns:
    """Paths that must answer correctly without reaching a provider."""

    async def test_designer_skips_composition_for_a_poll(self):
        brief = await DesignerAgent(session=None).run(
            design_request(content_type=ContentType.TELEGRAM_QUIZ)
        )
        assert brief.photo_needed is False
        assert brief.layout == "statement"

    async def test_analyst_reports_nothing_to_analyse(self):
        report = await AnalystAgent(session=None).run(
            AnalysisRequest(business=make_business(), production={"total": 0})
        )
        assert report.confidence == 0.0
        assert "post yo'q" in report.note

    async def test_video_editor_returns_an_unusable_plan_without_a_transcript(self):
        from app.agents.video_editor import VideoEditRequest, VideoEditorAgent

        plan = await VideoEditorAgent(session=None).run(
            VideoEditRequest(business=make_business(), segments=[], duration=20.0)
        )
        assert plan.is_usable is False
        assert plan.subtitle_style == "none"
