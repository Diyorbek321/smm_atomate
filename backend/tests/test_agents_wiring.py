"""Where the second-layer agents attach to the pipeline.

`test_agents_second_layer.py` covers what each agent does with a model's
answer. This file covers the other half: that the pipeline actually calls them,
passes the right thing along, and — the part that matters most — behaves
exactly as it did before when an agent is switched off or fails.

Every agent here is stubbed. The seam is the subject, not the model.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

import pytest

from app.agents.analyst import AnalysisReport, Finding
from app.agents.orchestrator import ContentPipeline
from app.agents.researcher import ResearchedFact, ResearchFindings
from app.core.config import settings
from app.models.enums import ContentItemStatus, ContentPillar, ContentType
from tests.test_agents import make_business, make_knowledge


def make_item(**kwargs):
    """A ContentItem with only the fields `production_stats` reads."""
    from app.models.content_item import ContentItem

    defaults = {
        "pillar": ContentPillar.EDUCATIONAL,
        "content_type": ContentType.FEED_POST,
        "status": ContentItemStatus.PUBLISHED,
        "quality_score": 8.0,
        "regeneration_count": 0,
        "topic": "mavzu",
    }
    return ContentItem(**{**defaults, **kwargs})


# --------------------------------------------------------------------------- #
# Analyst → marketolog
# --------------------------------------------------------------------------- #
class TestAnalystBrief:
    """`ContentPipeline._analysis` is the analyst's only caller."""

    @pytest.fixture
    def pipeline(self) -> ContentPipeline:
        return ContentPipeline(session=None)  # type: ignore[arg-type]

    @staticmethod
    def _stub(monkeypatch, *, items: list, report: AnalysisReport | None = None) -> dict:
        """Replace the query and the agent; record whether the agent ran."""
        from app.agents import orchestrator as module
        from app.repositories.content import ContentItemRepository

        calls: dict = {"ran": False, "request": None}

        async def fake_produced(self, business_id, *, days=30, limit=400):
            calls["days"] = days
            return items

        async def fake_run(self, request):
            calls["ran"] = True
            calls["request"] = request
            return report or AnalysisReport()

        monkeypatch.setattr(ContentItemRepository, "produced_between", fake_produced)
        monkeypatch.setattr(module.AnalystAgent, "run", fake_run)
        return calls

    async def test_off_by_flag_never_queries_or_calls(self, pipeline, monkeypatch):
        calls = self._stub(monkeypatch, items=[make_item()])
        monkeypatch.setattr(settings, "use_analyst_agent", False, raising=False)

        assert await pipeline._analysis(make_business(), {}) == ""
        assert calls["ran"] is False

    async def test_nothing_produced_skips_the_call(self, pipeline, monkeypatch):
        calls = self._stub(monkeypatch, items=[])
        monkeypatch.setattr(settings, "use_analyst_agent", True, raising=False)

        assert await pipeline._analysis(make_business(), {}) == ""
        assert calls["ran"] is False, "an empty month is not worth a pro-model call"

    async def test_recommendations_reach_the_brief(self, pipeline, monkeypatch):
        report = AnalysisReport(
            findings=[Finding(text="sotuv postlari kam reaksiya oldi", evidence="6 post")],
            recommendations=["Sotuv postini dalil bilan boshla"],
            confidence=0.6,
        )
        self._stub(monkeypatch, items=[make_item(), make_item()], report=report)
        monkeypatch.setattr(settings, "use_analyst_agent", True, raising=False)

        text = await pipeline._analysis(make_business(), {})
        assert "ANALITIK TAVSIYALARI" in text
        assert "Sotuv postini dalil bilan boshla" in text

    async def test_a_report_without_recommendations_adds_nothing(self, pipeline, monkeypatch):
        """Findings alone are an observation; the marketolog acts on advice."""
        report = AnalysisReport(findings=[Finding(text="hech narsa")], recommendations=[])
        self._stub(monkeypatch, items=[make_item()], report=report)
        monkeypatch.setattr(settings, "use_analyst_agent", True, raising=False)

        assert await pipeline._analysis(make_business(), {}) == ""

    async def test_the_agent_sees_the_production_stats_and_the_window(self, pipeline, monkeypatch):
        calls = self._stub(
            monkeypatch,
            items=[
                make_item(status=ContentItemStatus.REJECTED, quality_score=5.0),
                make_item(regeneration_count=2),
            ],
        )
        monkeypatch.setattr(settings, "use_analyst_agent", True, raising=False)
        monkeypatch.setattr(settings, "analyst_window_days", 45, raising=False)

        await pipeline._analysis(make_business(), {"published": 3})

        assert calls["days"] == 45
        request = calls["request"]
        assert request.days == 45
        assert request.production["total"] == 2
        assert request.production["rejected"] == 1
        assert request.production["regenerated"] == 1
        assert request.performance == {"published": 3}


# --------------------------------------------------------------------------- #
# Researcher → knowledge base
# --------------------------------------------------------------------------- #
class TestResearchOnIngest:
    """`OnboardingAgent` owns the structured fields; the researcher tops up notes."""

    @staticmethod
    def _stub(monkeypatch, findings: ResearchFindings) -> dict:
        from app.agents import onboarding as module

        calls: dict = {"ran": False, "request": None}

        async def fake_run(self, request):
            calls["ran"] = True
            calls["request"] = request
            return findings

        monkeypatch.setattr(module.ResearcherAgent, "run", fake_run)
        return calls

    @staticmethod
    def _findings(*pairs: tuple[str, str]) -> ResearchFindings:
        return ResearchFindings(
            facts=[
                ResearchedFact(label=label, value=value, source="ega aytdi", confidence=0.9)
                for label, value in pairs
            ]
        )

    async def test_off_by_flag_leaves_notes_untouched(self, monkeypatch):
        from app.agents.onboarding import OnboardingAgent

        calls = self._stub(monkeypatch, self._findings(("Narx", "600000 so'm")))
        monkeypatch.setattr(settings, "use_researcher_agent", False, raising=False)
        knowledge = make_knowledge()
        knowledge.raw_notes = "boshlang'ich"

        result = await OnboardingAgent(session=None).research(
            make_business(), knowledge, text="x" * 900
        )

        assert result == {}
        assert calls["ran"] is False
        assert knowledge.raw_notes == "boshlang'ich"

    async def test_short_chat_messages_are_not_mined(self, monkeypatch):
        from app.agents.onboarding import OnboardingAgent

        calls = self._stub(monkeypatch, self._findings(("Narx", "600000 so'm")))
        monkeypatch.setattr(settings, "use_researcher_agent", True, raising=False)
        monkeypatch.setattr(settings, "research_min_chars", 400, raising=False)

        result = await OnboardingAgent(session=None).research(
            make_business(), make_knowledge(), text="Narx 600 ming"
        )

        assert result == {}
        assert calls["ran"] is False, "a one-line reply is onboarding's job, not research"

    async def test_a_document_is_always_worth_mining(self, monkeypatch):
        """Length gates text, never a document — a PDF is why this exists."""
        from app.agents.onboarding import OnboardingAgent

        calls = self._stub(monkeypatch, self._findings(("Backend kursi", "800000 so'm/oy")))
        monkeypatch.setattr(settings, "use_researcher_agent", True, raising=False)
        knowledge = make_knowledge()

        result = await OnboardingAgent(session=None).research(
            make_business(), knowledge, text="", document=("application/pdf", b"%PDF-1.4")
        )

        assert calls["ran"] is True
        assert calls["request"].document == ("application/pdf", b"%PDF-1.4")
        assert result["added"] == 1
        assert "800000" in (knowledge.raw_notes or "")

    async def test_long_text_is_mined_and_merged(self, monkeypatch):
        from app.agents.onboarding import OnboardingAgent

        self._stub(monkeypatch, self._findings(("IELTS intensiv", "600000 so'm")))
        monkeypatch.setattr(settings, "use_researcher_agent", True, raising=False)
        monkeypatch.setattr(settings, "research_min_chars", 400, raising=False)
        knowledge = make_knowledge()
        knowledge.raw_notes = "Markaz 2019 yildan beri ishlaydi."

        result = await OnboardingAgent(session=None).research(
            make_business(), knowledge, text="narxlar ro'yxati " * 40
        )

        assert result["added"] == 1
        assert "Markaz 2019 yildan beri ishlaydi." in knowledge.raw_notes
        assert "TADQIQOT FAKTLARI:" in knowledge.raw_notes

    async def test_known_facts_are_sent_so_they_are_not_returned_again(self, monkeypatch):
        from app.agents.onboarding import OnboardingAgent

        calls = self._stub(monkeypatch, ResearchFindings())
        monkeypatch.setattr(settings, "use_researcher_agent", True, raising=False)
        knowledge = make_knowledge()

        await OnboardingAgent(session=None).research(
            make_business(), knowledge, text="", document=("application/pdf", b"%PDF")
        )

        assert calls["request"].known_facts, "the knowledge base already holds prices"

    async def test_ingest_runs_the_researcher_on_what_it_just_read(self, monkeypatch):
        """The wiring itself: onboarding's text path reaches the researcher."""
        from app.agents.onboarding import OnboardingAgent
        from app.schemas.knowledge_base import KnowledgeExtraction

        seen: dict = {}

        async def fake_ask_json(self, prompt, schema, **kwargs):
            return KnowledgeExtraction(summary="ok")

        async def fake_research(self, business, knowledge, *, text="", document=None, source=""):
            seen["text"] = text
            seen["document"] = document
            return {"added": 2}

        monkeypatch.setattr(OnboardingAgent, "ask_json", fake_ask_json)
        monkeypatch.setattr(OnboardingAgent, "research", fake_research)

        result = await OnboardingAgent(session=None).ingest(
            make_business(), make_knowledge(), "narxlar ro'yxati"
        )

        assert seen["text"] == "narxlar ro'yxati"
        assert seen["document"] is None
        assert result.research == {"added": 2}

    async def test_ingest_document_hands_the_file_to_the_researcher(self, monkeypatch):
        from app.agents.onboarding import OnboardingAgent
        from app.schemas.knowledge_base import KnowledgeExtraction

        seen: dict = {}

        async def fake_ask_json(self, prompt, schema, **kwargs):
            return KnowledgeExtraction(summary="ok")

        async def fake_research(self, business, knowledge, *, text="", document=None, source=""):
            seen["document"] = document
            return {"added": 1}

        monkeypatch.setattr(OnboardingAgent, "ask_json", fake_ask_json)
        monkeypatch.setattr(OnboardingAgent, "research", fake_research)

        result = await OnboardingAgent(session=None).ingest_document(
            make_business(), make_knowledge(), b"%PDF-1.4 narx", filename="narxlar.pdf"
        )

        assert seen["document"] == ("application/pdf", b"%PDF-1.4 narx")
        assert result.research == {"added": 1}

    async def test_a_failing_researcher_does_not_break_ingest(self, monkeypatch):
        from app.agents import onboarding as module
        from app.agents.onboarding import OnboardingAgent

        async def boom(self, request):
            raise RuntimeError("provider down")

        monkeypatch.setattr(module.ResearcherAgent, "run", boom)
        monkeypatch.setattr(settings, "use_researcher_agent", True, raising=False)
        knowledge = make_knowledge()
        knowledge.raw_notes = "asl"

        result = await OnboardingAgent(session=None).research(
            make_business(), knowledge, text="", document=("application/pdf", b"%PDF")
        )

        assert result == {}
        assert knowledge.raw_notes == "asl"


# --------------------------------------------------------------------------- #
# Video editor → the cut
# --------------------------------------------------------------------------- #
class TestPlannedCut:
    """`plan_cut` turns an agent plan into the segment list ffmpeg takes."""

    @staticmethod
    def _stub(monkeypatch, plan) -> dict:
        from app.tasks import generation as module

        calls: dict = {"ran": False, "request": None}

        async def fake_run(self, request):
            calls["ran"] = True
            calls["request"] = request
            return plan

        monkeypatch.setattr(module.VideoEditorAgent, "run", fake_run)
        return calls

    async def test_off_by_flag_falls_back_to_silence_trim(self, monkeypatch):
        from app.agents.video_editor import EditPlan, KeepSegment
        from app.tasks.generation import plan_cut

        calls = self._stub(monkeypatch, EditPlan(keep=[KeepSegment(start=0.0, end=5.0)]))
        monkeypatch.setattr(settings, "use_video_editor_agent", False, raising=False)

        assert await plan_cut(None, make_business(), b"video", topic="x") is None
        assert calls["ran"] is False

    async def test_an_unusable_plan_falls_back_to_silence_trim(self, monkeypatch):
        from app.agents.video_editor import EditPlan
        from app.tasks import generation as module
        from app.tasks.generation import plan_cut

        self._stub(monkeypatch, EditPlan(keep=[]))
        monkeypatch.setattr(settings, "use_video_editor_agent", True, raising=False)

        async def fake_transcribe(source):
            return [{"start": 0.0, "end": 4.0, "text": "salom"}], 30.0

        monkeypatch.setattr(module, "_transcribe_source", fake_transcribe)

        assert await plan_cut(None, make_business(), b"video", topic="x") is None

    async def test_a_usable_plan_becomes_keep_segments(self, monkeypatch):
        from app.agents.video_editor import EditPlan, KeepSegment
        from app.tasks import generation as module
        from app.tasks.generation import plan_cut

        plan = EditPlan(
            keep=[KeepSegment(start=2.0, end=9.0), KeepSegment(start=14.0, end=20.0)]
        )
        calls = self._stub(monkeypatch, plan)
        monkeypatch.setattr(settings, "use_video_editor_agent", True, raising=False)

        async def fake_transcribe(source):
            return [{"start": 0.0, "end": 4.0, "text": "salom"}], 30.0

        monkeypatch.setattr(module, "_transcribe_source", fake_transcribe)

        segments = await plan_cut(None, make_business(), b"video", topic="narx")

        assert segments == [(2.0, 9.0), (14.0, 20.0)]
        assert calls["request"].duration == 30.0
        assert calls["request"].topic == "narx"

    async def test_no_transcript_never_reaches_the_agent(self, monkeypatch):
        from app.agents.video_editor import EditPlan, KeepSegment
        from app.tasks import generation as module
        from app.tasks.generation import plan_cut

        calls = self._stub(monkeypatch, EditPlan(keep=[KeepSegment(start=0.0, end=5.0)]))
        monkeypatch.setattr(settings, "use_video_editor_agent", True, raising=False)

        async def fake_transcribe(source):
            return [], 30.0

        monkeypatch.setattr(module, "_transcribe_source", fake_transcribe)

        assert await plan_cut(None, make_business(), b"video", topic="x") is None
        assert calls["ran"] is False

    async def test_a_failing_transcription_falls_back_quietly(self, monkeypatch):
        from app.agents.video_editor import EditPlan, KeepSegment
        from app.tasks import generation as module
        from app.tasks.generation import plan_cut

        self._stub(monkeypatch, EditPlan(keep=[KeepSegment(start=0.0, end=5.0)]))
        monkeypatch.setattr(settings, "use_video_editor_agent", True, raising=False)

        async def boom(source):
            raise RuntimeError("whisper is down")

        monkeypatch.setattr(module, "_transcribe_source", boom)

        assert await plan_cut(None, make_business(), b"video", topic="x") is None


# --------------------------------------------------------------------------- #
# The planned cut, once it reaches the encoder
# --------------------------------------------------------------------------- #
class TestClampSegments:
    """`edit_video` takes the agent's plan; this is what it does with it."""

    def test_a_plan_inside_the_file_survives_intact(self):
        from app.services.video_editor import clamp_segments

        assert clamp_segments([(2.0, 9.0), (14.0, 20.0)], 30.0) == [(2.0, 9.0), (14.0, 20.0)]

    def test_an_end_past_the_file_is_clipped_not_dropped(self):
        """Transcripts routinely end a fraction past the media; keep the take."""
        from app.services.video_editor import clamp_segments

        assert clamp_segments([(2.0, 31.4)], 30.0) == [(2.0, 30.0)]

    def test_a_segment_shorter_than_a_frame_is_dropped(self):
        from app.services.video_editor import clamp_segments

        assert clamp_segments([(2.0, 2.1)], 30.0) == []

    def test_a_reversed_pair_is_dropped(self):
        from app.services.video_editor import clamp_segments

        assert clamp_segments([(9.0, 2.0)], 30.0) == []

    def test_a_segment_wholly_past_the_file_is_dropped(self):
        from app.services.video_editor import clamp_segments

        assert clamp_segments([(40.0, 50.0), (1.0, 6.0)], 30.0) == [(1.0, 6.0)]

    def test_an_unprobeable_file_keeps_nothing(self):
        from app.services.video_editor import clamp_segments

        assert clamp_segments([(1.0, 6.0)], 0.0) == []


class TestPlanReachesTheEncoder:
    """The last link: `run_video_edit` hands the planned cut to ffmpeg.

    Everything around the edit is stubbed — storage, the session, the review
    push. The subject is one argument: that `keep` is what `plan_cut` decided,
    and that the deterministic trim still runs when it decided nothing.
    """

    @staticmethod
    def _harness(monkeypatch, tmp_path, planned):
        import contextlib

        from app.tasks import generation as module

        seen: dict = {}

        class Stored:
            url = "/media/edited.mp4"

        class Storage:
            root = tmp_path

            def save_bytes(self, data, *, prefix, content_type):
                return Stored()

        class Report:
            source_seconds = 30.0
            final_seconds = 12.0
            trimmed_seconds = 18.0
            subtitle_lines = 4
            stages: ClassVar[list] = []
            skipped: ClassVar[list] = []

        class Session:
            async def flush(self):
                return None

        @contextlib.asynccontextmanager
        async def scope():
            yield Session()

        class Repo:
            def __init__(self, session):
                pass

            async def get_full_or_404(self, business_id):
                business = make_business()
                business.settings = {"plan": "pro"}
                return business

            async def get_or_create(self, business_id):
                return make_knowledge()

        async def fake_plan_cut(session, business, source, *, topic=""):
            seen["topic"] = topic
            return planned

        async def fake_edit_video(source, **kwargs):
            seen["keep"] = kwargs.get("keep")
            return b"mp4", None, Report()

        async def fake_item(session, business, video_url, cover_url, caption, report):
            class Item:
                id = "00000000-0000-0000-0000-000000000000"

            return Item()

        async def fake_push(session, business, items):
            return None

        monkeypatch.setattr(module, "session_scope", scope)
        monkeypatch.setattr(module, "BusinessRepository", Repo)
        monkeypatch.setattr(module, "plan_cut", fake_plan_cut)
        monkeypatch.setattr(module, "_video_item", fake_item)
        monkeypatch.setattr(module, "push_items_for_review", fake_push)
        monkeypatch.setattr("app.repositories.business.KnowledgeBaseRepository", Repo)
        monkeypatch.setattr("app.services.storage.get_storage", lambda: Storage())
        monkeypatch.setattr("app.services.video_editor.edit_video", fake_edit_video)

        (tmp_path / "clip.mp4").write_bytes(b"fake video")
        return seen

    async def test_the_planned_cut_is_what_ffmpeg_is_given(self, monkeypatch, tmp_path):
        from app.tasks.generation import run_video_edit

        seen = self._harness(monkeypatch, tmp_path, [(2.0, 9.0), (14.0, 20.0)])

        await run_video_edit(str(uuid.uuid4()), "clip.mp4", caption="narx haqida")

        assert seen["keep"] == [(2.0, 9.0), (14.0, 20.0)]
        assert seen["topic"] == "narx haqida"

    async def test_no_plan_leaves_the_silence_trim_in_charge(self, monkeypatch, tmp_path):
        from app.tasks.generation import run_video_edit

        seen = self._harness(monkeypatch, tmp_path, None)

        await run_video_edit(str(uuid.uuid4()), "clip.mp4", caption="")

        assert seen["keep"] is None
