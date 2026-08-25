"""The scout's deterministic half, and where it attaches to planning.

The model's answer is not testable without a provider. What is testable — and
where the damage would be — is the clamping around it: that a competitor's
sentence cannot come back out, that a one-channel habit cannot be sold as a
niche trend, and that a business with no competitors listed plans exactly as it
did before any of this existed.
"""

from __future__ import annotations

from app.agents.orchestrator import ContentPipeline
from app.agents.scout import (
    MIN_CHANNELS_FOR_TREND,
    ScoutAgent,
    ScoutRequest,
    TrendReport,
    TrendTheme,
)
from app.core.config import settings
from app.services.telegram_scout import ChannelSnapshot, ScoutPost
from tests.test_agents import make_business, make_knowledge


def snapshot(handle: str = "raqobat", *texts: str, views: int = 100) -> ChannelSnapshot:
    snap = ChannelSnapshot(
        handle=handle,
        subscribers=3400,
        posts=[ScoutPost(handle=handle, text=t, views=views) for t in texts],
    )
    snap.rank()
    return snap


# --------------------------------------------------------------------------- #
# The copy guard
# --------------------------------------------------------------------------- #
class TestNothingIsCopied:
    """A client publishing a rival's line is the one outcome that costs money."""

    def test_a_lifted_sentence_is_dropped(self):
        source = snapshot("raqobat", "Bizning o'quvchimiz IELTS 7.5 ball oldi tabriklaymiz")
        report = TrendReport(
            themes=[
                TrendTheme(topic="Bizning o'quvchimiz IELTS 7.5 ball oldi", channels=2),
                TrendTheme(topic="bitiruvchi o'z sertifikatini ko'rsatadi", channels=2),
            ]
        )

        cleaned = ScoutAgent._sanitise(report, [source])

        topics = [t.topic for t in cleaned.themes]
        assert "bitiruvchi o'z sertifikatini ko'rsatadi" in topics
        assert not any("7.5 ball oldi" in t for t in topics)

    def test_reworded_copy_is_still_copy(self):
        """Jaccard over content words, so a synonym swap does not get through."""
        source = snapshot("raqobat", "Sentabr guruhiga qabul boshlandi shoshiling")
        report = TrendReport(gaps=["Sentabr guruhiga qabul ochildi shoshiling"])

        assert ScoutAgent._sanitise(report, [source]).gaps == []

    def test_a_genuine_theme_survives(self):
        source = snapshot("raqobat", "Bizning o'quvchimiz IELTS 7.5 ball oldi")
        report = TrendReport(gaps=["narx ochiq aytilmaydi"], saturated=["sentabr chegirmasi"])

        cleaned = ScoutAgent._sanitise(report, [source])
        assert cleaned.gaps == ["narx ochiq aytilmaydi"]
        assert cleaned.saturated == ["sentabr chegirmasi"]

    def test_the_guard_reads_every_post_not_just_the_outperformers(self):
        """An ordinary post is still somebody's copy."""
        source = ChannelSnapshot(
            handle="raqobat",
            posts=[
                ScoutPost(handle="raqobat", text="oddiy post", views=100),
                ScoutPost(handle="raqobat", text="Kelasi hafta ochiq eshiklar kuni bo'ladi", views=90),
            ],
        )
        source.rank()
        report = TrendReport(gaps=["Kelasi hafta ochiq eshiklar kuni bo'ladi"])

        assert ScoutAgent._sanitise(report, [source]).gaps == []


class TestCorpus:
    """What the model is shown, and what it is deliberately not shown."""

    def test_each_post_is_one_row(self):
        """A post's own line breaks would read as extra, unlabelled posts."""
        snap = ChannelSnapshot(
            handle="raqobat",
            posts=[
                ScoutPost(handle="raqobat", text="Sarlavha\n\nIkkinchi qator", views=400),
                ScoutPost(handle="raqobat", text="oddiy", views=100),
                ScoutPost(handle="raqobat", text="oddiy", views=100),
                ScoutPost(handle="raqobat", text="oddiy", views=100),
            ],
        )
        snap.rank()

        rows = [r for r in ScoutAgent._corpus([snap]).splitlines() if r.startswith("-")]
        assert len(rows) == 1
        assert "Sarlavha Ikkinchi qator" in rows[0]

    def test_only_a_preview_of_the_text_is_shown(self):
        """The truncation is a guardrail against lifting copy, not a saving."""
        from app.agents.scout import POST_PREVIEW_CHARS

        long_post = "so'z " * 200
        snap = ChannelSnapshot(
            handle="raqobat",
            posts=[ScoutPost(handle="raqobat", text=long_post, views=400)]
            + [ScoutPost(handle="raqobat", text="oddiy", views=100) for _ in range(3)],
        )
        snap.rank()

        row = next(r for r in ScoutAgent._corpus([snap]).splitlines() if r.startswith("-"))
        assert len(row) < POST_PREVIEW_CHARS + 60

    def test_lift_is_shown_rather_than_raw_views(self):
        """Raw views would rank a big channel's ordinary post above a small hit."""
        snap = ChannelSnapshot(
            handle="raqobat",
            posts=[ScoutPost(handle="raqobat", text="hit", views=400)]
            + [ScoutPost(handle="raqobat", text="oddiy", views=100) for _ in range(3)],
        )
        snap.rank()

        row = next(r for r in ScoutAgent._corpus([snap]).splitlines() if r.startswith("-"))
        assert "4.0x" in row
        assert "400" not in row

    def test_a_channel_with_nothing_outstanding_contributes_no_block(self):
        flat = snapshot("raqobat", "bir", "ikki", "uch", "tort")
        assert ScoutAgent._corpus([flat]) == ""


# --------------------------------------------------------------------------- #
# Evidence discipline
# --------------------------------------------------------------------------- #
class TestEvidence:
    def test_a_claimed_channel_count_cannot_exceed_what_was_read(self):
        report = TrendReport(themes=[TrendTheme(topic="video darslar", channels=9)])
        cleaned = ScoutAgent._sanitise(report, [snapshot("bir", "x"), snapshot("ikki", "y")])
        assert cleaned.themes[0].channels == 2

    def test_a_single_channel_theme_is_kept_but_not_briefed(self):
        """One channel is that channel's habit; the brief only carries a niche."""
        report = TrendReport(
            themes=[
                TrendTheme(topic="faqat bitta kanalda", channels=1),
                TrendTheme(topic="ikkitasida ham bor", channels=2),
            ]
        )
        cleaned = ScoutAgent._sanitise(report, [snapshot("bir", "x"), snapshot("ikki", "y")])

        assert len(cleaned.themes) == 2, "kept, so the note can still mention it"
        instructions = cleaned.as_instructions()
        assert "ikkitasida ham bor" in instructions
        assert "faqat bitta kanalda" not in instructions

    def test_the_threshold_is_two(self):
        assert MIN_CHANNELS_FOR_TREND == 2

    def test_lists_are_capped(self):
        report = TrendReport(
            themes=[TrendTheme(topic=f"mavzu {i}", channels=2) for i in range(9)],
            gaps=[f"bo'shliq {i}" for i in range(9)],
            saturated=[f"qovushgan {i}" for i in range(9)],
            formats=[f"format {i}" for i in range(9)],
        )
        cleaned = ScoutAgent._sanitise(report, [snapshot("bir", "x")])

        assert len(cleaned.themes) == 5
        assert len(cleaned.gaps) == 4
        assert len(cleaned.saturated) == 4
        assert len(cleaned.formats) == 3


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
class TestInstructions:
    def test_an_empty_report_says_nothing(self):
        assert TrendReport().as_instructions() == ""
        assert TrendReport(note="hech narsa topilmadi").as_instructions() == ""

    def test_every_section_is_labelled(self):
        text = TrendReport(
            themes=[TrendTheme(topic="natija posti", why="ishonch beradi", channels=3)],
            formats=["video"],
            gaps=["narx haqida hech kim gapirmaydi"],
            saturated=["sentabr chegirmasi"],
        ).as_instructions()

        assert "QO'SHNILARDA ISHLAYAPTI" in text and "3 kanalda" in text
        assert "KO'PROQ KO'RILGAN FORMAT: video" in text
        assert "HECH KIM YOPMAGAN" in text
        assert "TAKRORLAMA" in text

    def test_empty_sections_are_dropped_not_shown_blank(self):
        text = TrendReport(gaps=["bitta bo'shliq"]).as_instructions()
        assert "HECH KIM YOPMAGAN" in text
        assert "FORMAT" not in text and "TAKRORLAMA" not in text


# --------------------------------------------------------------------------- #
# Early returns — no provider reached
# --------------------------------------------------------------------------- #
class TestEarlyReturns:
    async def test_no_channels_read(self):
        report = await ScoutAgent(session=None).run(
            ScoutRequest(business=make_business(), knowledge=None, snapshots=[])
        )
        assert report.is_usable is False
        assert "ma'lumot yo'q" in report.note

    async def test_a_channel_too_thin_to_rank_is_not_analysed(self):
        thin = snapshot("raqobat", "bitta post")
        report = await ScoutAgent(session=None).run(
            ScoutRequest(business=make_business(), knowledge=None, snapshots=[thin])
        )
        assert report.is_usable is False

    async def test_channels_with_no_outperformers_stop_before_the_call(self):
        """Every post at the median: readable, ranked, and says nothing."""
        flat = snapshot("raqobat", "bir", "ikki", "uch", "tort")
        assert flat.is_usable is True
        report = await ScoutAgent(session=None).run(
            ScoutRequest(business=make_business(), knowledge=None, snapshots=[flat])
        )
        assert "ajralib chiqqan post yo'q" in report.note


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #
class TestTrendsWiring:
    """`ContentPipeline._trends` is the scout's only caller."""

    @staticmethod
    def _stub(monkeypatch, *, snapshots: list, report: TrendReport | None = None) -> dict:
        from app.agents import orchestrator as module

        calls: dict = {"scouted": None, "ran": False, "limit": None}

        async def fake_scout(handles, *, limit=5):
            calls["scouted"] = list(handles)
            calls["limit"] = limit
            return snapshots

        async def fake_run(self, request):
            calls["ran"] = True
            calls["request"] = request
            return report or TrendReport()

        monkeypatch.setattr(module, "scout", fake_scout)
        monkeypatch.setattr(module.ScoutAgent, "run", fake_run)
        return calls

    def _knowledge(self, competitors):
        knowledge = make_knowledge()
        knowledge.competitors = competitors
        return knowledge

    async def test_off_by_flag_never_fetches(self, monkeypatch):
        calls = self._stub(monkeypatch, snapshots=[snapshot("raqobat", "x")])
        monkeypatch.setattr(settings, "use_scout_agent", False, raising=False)

        pipeline = ContentPipeline(session=None)  # type: ignore[arg-type]
        assert await pipeline._trends(make_business(), self._knowledge(["@raqobat"])) == ""
        assert calls["scouted"] is None

    async def test_no_competitors_listed_means_no_network_call(self, monkeypatch):
        """The state every business starts in — planning must be unchanged."""
        calls = self._stub(monkeypatch, snapshots=[])
        monkeypatch.setattr(settings, "use_scout_agent", True, raising=False)

        pipeline = ContentPipeline(session=None)  # type: ignore[arg-type]
        assert await pipeline._trends(make_business(), self._knowledge([])) == ""
        assert calls["scouted"] is None
        assert calls["ran"] is False

    async def test_unreadable_channels_stop_before_the_agent(self, monkeypatch):
        calls = self._stub(monkeypatch, snapshots=[])
        monkeypatch.setattr(settings, "use_scout_agent", True, raising=False)

        pipeline = ContentPipeline(session=None)  # type: ignore[arg-type]
        assert await pipeline._trends(make_business(), self._knowledge(["Najot Ta'lim"])) == ""
        assert calls["ran"] is False, "no snapshots is not worth a pro-model call"

    async def test_the_report_reaches_the_brief(self, monkeypatch):
        report = TrendReport(
            themes=[TrendTheme(topic="natija posti", channels=3)],
            gaps=["narx haqida hech kim gapirmaydi"],
        )
        self._stub(monkeypatch, snapshots=[snapshot("raqobat", "x")], report=report)
        monkeypatch.setattr(settings, "use_scout_agent", True, raising=False)

        pipeline = ContentPipeline(session=None)  # type: ignore[arg-type]
        text = await pipeline._trends(make_business(), self._knowledge(["@raqobat"]))

        assert "RAZVEDKA" in text
        assert "natija posti" in text
        assert "narx haqida hech kim gapirmaydi" in text

    async def test_the_channel_cap_comes_from_settings(self, monkeypatch):
        calls = self._stub(monkeypatch, snapshots=[snapshot("raqobat", "x")])
        monkeypatch.setattr(settings, "use_scout_agent", True, raising=False)
        monkeypatch.setattr(settings, "scout_max_channels", 2, raising=False)

        pipeline = ContentPipeline(session=None)  # type: ignore[arg-type]
        await pipeline._trends(make_business(), self._knowledge(["@bir", "@ikki", "@uch"]))

        assert calls["limit"] == 2
        assert calls["scouted"] == ["@bir", "@ikki", "@uch"]

    async def test_a_missing_knowledge_base_is_not_a_crash(self, monkeypatch):
        calls = self._stub(monkeypatch, snapshots=[])
        monkeypatch.setattr(settings, "use_scout_agent", True, raising=False)

        pipeline = ContentPipeline(session=None)  # type: ignore[arg-type]
        assert await pipeline._trends(make_business(), None) == ""
        assert calls["scouted"] is None


# --------------------------------------------------------------------------- #
# Where the channels come from
# --------------------------------------------------------------------------- #
class TestCompetitorsAreCollected:
    """The scout reads `KnowledgeBase.competitors`; nothing used to fill it.

    The field existed on the model and in the update schema, but not in the
    shape the onboarding agent returns — so onboarding could never populate it
    and the list stayed empty for every business.
    """

    @staticmethod
    def _extraction(*competitors: str):
        from app.schemas.knowledge_base import KnowledgeExtraction

        return KnowledgeExtraction(competitors=list(competitors))

    def test_the_extraction_shape_carries_competitors(self):
        assert self._extraction("@birkanal").competitors == ["@birkanal"]

    def test_merge_appends_without_losing_what_is_there(self):
        from app.agents.onboarding import OnboardingAgent

        knowledge = make_knowledge()
        knowledge.competitors = ["@birkanal"]
        updated = OnboardingAgent.merge(knowledge, self._extraction("@ikkikanal"))

        assert knowledge.competitors == ["@birkanal", "@ikkikanal"]
        assert "competitors" in updated

    def test_the_same_channel_in_three_shapes_is_one_competitor(self):
        from app.agents.onboarding import OnboardingAgent

        knowledge = make_knowledge()
        knowledge.competitors = ["@najottalim"]
        OnboardingAgent.merge(knowledge, self._extraction("t.me/najottalim", "https://t.me/najottalim"))

        assert knowledge.competitors == ["@najottalim"]

    def test_a_name_is_kept_as_typed(self):
        """Unresolvable, but it is what the owner will be asked about."""
        from app.agents.onboarding import OnboardingAgent

        knowledge = make_knowledge()
        knowledge.competitors = []
        OnboardingAgent.merge(knowledge, self._extraction("Najot Ta'lim"))

        assert knowledge.competitors == ["Najot Ta'lim"]

    def test_the_list_is_capped(self):
        from app.agents.onboarding import OnboardingAgent

        knowledge = make_knowledge()
        knowledge.competitors = []
        OnboardingAgent.merge(knowledge, self._extraction(*[f"@kanal{i:02d}" for i in range(30)]))

        assert len(knowledge.competitors) == 12

    @staticmethod
    def _complete_except_competitors():
        """A profile with only the competitor list still open."""
        knowledge = make_knowledge()
        knowledge.faq = [{"q": "Qachon?", "a": "18:00"}]
        knowledge.teacher_profiles = [{"name": "Aziz", "role": "IELTS"}]
        knowledge.competitors = []
        assert knowledge.missing_fields == ["competitors"]
        return knowledge

    def test_the_owner_is_asked_for_the_link_not_the_name(self):
        from app.agents.onboarding import OnboardingAgent

        question = OnboardingAgent.fallback_question(self._complete_except_competitors())

        assert question is not None
        assert "HAVOLASINI" in question

    def test_the_question_comes_after_everything_else(self):
        """It is the one answer an owner may not have to hand."""
        from app.agents.onboarding import INTERVIEW_QUESTIONS

        assert INTERVIEW_QUESTIONS[-1][0] == "competitors"

    def test_a_filled_list_stops_the_question(self):
        from app.agents.onboarding import OnboardingAgent

        knowledge = self._complete_except_competitors()
        knowledge.competitors = ["@birkanal"]
        assert OnboardingAgent.fallback_question(knowledge) is None

    def test_completeness_is_deliberately_untouched(self):
        """Adding an eighth check would move every existing profile's score."""
        knowledge = make_knowledge()
        knowledge.competitors = []
        without = knowledge.compute_completeness()
        knowledge.competitors = ["@birkanal"]

        assert knowledge.compute_completeness() == without
        assert "competitors" in knowledge.missing_fields or knowledge.competitors
