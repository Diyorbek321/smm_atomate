"""EditorAgent — deterministic checks + LLM self-reflection before review."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agents.base import BaseAgent, knowledge_context
from app.agents.prompts import EDITOR_SYSTEM
from app.core.logging import get_logger
from app.models.business import Business
from app.models.enums import ContentType
from app.models.knowledge_base import KnowledgeBase
from app.schemas.content import CopyOutput, EditorIssue, EditorOutput
from app.utils.text import (
    IG_CAPTION_LIMIT,
    IG_HASHTAG_LIMIT,
    TG_MESSAGE_LIMIT,
    dedupe_phone,
    find_placeholders,
    find_robotic_phrases,
    normalize_apostrophes,
    truncate_caption,
    word_count,
)

log = get_logger(__name__)

#: Below this score the item is regenerated instead of sent for review.
PASS_SCORE = 7.0
MIN_CAPTION_WORDS = 12


@dataclass(slots=True)
class EditorRequest:
    business: Business
    knowledge: KnowledgeBase | None
    copy: CopyOutput
    content_type: ContentType
    topic: str
    deep_check: bool = True   # set False to run only the local rules (fast/offline)


@dataclass(slots=True)
class EditorResult:
    copy: CopyOutput
    report: EditorOutput
    issues: list[EditorIssue] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.report.approved

    @property
    def score(self) -> float:
        return self.report.score

    @property
    def has_critical(self) -> bool:
        return any(issue.severity == "critical" for issue in self.report.issues)


class EditorAgent(BaseAgent):
    name = "editor"

    async def run(self, request: EditorRequest) -> EditorResult:
        local_issues = self.static_checks(request)

        report = EditorOutput(
            approved=True,
            score=round(max(0.0, 10.0 - self._penalty(local_issues)), 2),
            issues=list(local_issues),
            summary="",
        )

        if request.deep_check:
            try:
                llm_report = await self._reflect(request)
                report = self._merge(report, llm_report, local_issues)
            except Exception as exc:
                log.warning("editor_reflection_failed", error=str(exc)[:200])
                report.summary = f"LLM tekshiruvi o'tkazilmadi: {str(exc)[:120]}"

        copy = self._tidy_contacts(self._apply_fixes(request.copy, report), request.knowledge)
        report.approved = report.score >= PASS_SCORE and not any(
            i.severity == "critical" for i in report.issues
        )
        log.info(
            "editor_verdict",
            approved=report.approved,
            score=report.score,
            issues=len(report.issues),
            content_type=request.content_type.value,
        )
        return EditorResult(copy=copy, report=report, issues=report.issues)

    # ------------------------------------------------------------------ #
    # Deterministic rules — cheap, always run, never hallucinate.
    # ------------------------------------------------------------------ #
    def static_checks(self, request: EditorRequest) -> list[EditorIssue]:
        issues: list[EditorIssue] = []
        copy = request.copy
        kb = request.knowledge

        def add(severity: str, field_name: str, problem: str, suggestion: str = "") -> None:
            issues.append(
                EditorIssue(severity=severity, field=field_name, problem=problem, suggestion=suggestion)
            )

        for field_name, text, limit in (
            ("caption_tg", copy.caption_tg, TG_MESSAGE_LIMIT),
            ("caption_ig", copy.caption_ig, IG_CAPTION_LIMIT),
        ):
            if not text.strip():
                add("critical", field_name, "Matn bo'sh", "Postni qayta yarating")
                continue
            if len(text) > limit:
                add("major", field_name, f"Uzunlik {len(text)} > {limit}", "Matnni qisqartiring")
            if word_count(text) < MIN_CAPTION_WORDS:
                add("major", field_name, "Matn juda qisqa", "Kamida 2-3 gap yozing")
            for placeholder in find_placeholders(text):
                add("critical", field_name, f"To'ldirilmagan joy: {placeholder}", "Aniq qiymat bilan almashtiring")
            for phrase in find_robotic_phrases(text):
                add("major", field_name, f"Sun'iy ibora: '{phrase}'", "Jonli tilga o'zgartiring")

        if not copy.cta.strip():
            add("major", "cta", "CTA yo'q", "Aniq harakatga chorlov qo'shing")

        contact_tokens = [t for t in [kb.phone if kb else None, kb.telegram_username if kb else None] if t]
        if contact_tokens and not any(
            token.lstrip("@") in copy.caption_tg for token in contact_tokens
        ):
            add("major", "caption_tg", "Aloqa ma'lumoti yo'q", "Telefon yoki username qo'shing")

        if len(copy.hashtags) > IG_HASHTAG_LIMIT:
            add("minor", "hashtags", f"{len(copy.hashtags)} ta hashtag (max {IG_HASHTAG_LIMIT})", "Kamaytiring")
        if len({h.lower() for h in copy.hashtags}) != len(copy.hashtags):
            add("minor", "hashtags", "Takrorlangan hashtag bor", "Dublikatlarni olib tashlang")

        if kb and kb.banned_topics:
            # Whole-word match only: "din" must not fire inside "farzandining".
            lowered = (copy.caption_tg + " " + copy.caption_ig).lower()
            for topic in kb.banned_topics:
                if topic and re.search(rf"(?<![\w'])({re.escape(topic.lower())})(?![\w'])", lowered):
                    add("critical", "caption", f"Taqiqlangan mavzu: {topic}", "Mavzuni olib tashlang")

        if request.content_type == ContentType.CAROUSEL:
            if len(copy.slides) < 3:
                add("critical", "slides", f"Karuselda {len(copy.slides)} ta slayd (min 3)", "Slayd qo'shing")
            for slide in copy.slides:
                if len(str(slide.get("title", ""))) > 70:
                    add("minor", "slides", f"Slayd {slide.get('index')} sarlavhasi uzun", "60 belgigacha qisqarting")

        if request.content_type == ContentType.TELEGRAM_QUIZ:
            quiz = copy.quiz or {}
            answers = quiz.get("answers") or []
            if len(answers) < 2:
                add("critical", "quiz", "Quizda 2 tadan kam javob", "Kamida 3 ta variant bering")
            correct = quiz.get("correct_option_id", 0)
            if not isinstance(correct, int) or not 0 <= correct < max(1, len(answers)):
                add("critical", "quiz", "To'g'ri javob indeksi noto'g'ri", "0..N-1 oralig'ida bo'lsin")

        if request.content_type == ContentType.REELS_SCRIPT and not (copy.script or {}).get("scenes"):
            add("major", "script", "Reels ssenariysida sahnalar yo'q", "Sahnalar ro'yxatini qo'shing")

        return issues

    @staticmethod
    def _penalty(issues: list[EditorIssue]) -> float:
        weights = {"critical": 4.0, "major": 1.5, "minor": 0.4}
        return sum(weights.get(issue.severity, 0.5) for issue in issues)

    # ------------------------------------------------------------------ #
    async def _reflect(self, request: EditorRequest) -> EditorOutput:
        system = await self.system_prompt(EDITOR_SYSTEM, business_id=request.business.id)
        copy = request.copy
        prompt = "\n\n".join(
            [
                knowledge_context(request.business, request.knowledge),
                f"FORMAT: {request.content_type.value}\nMAVZU: {request.topic}",
                f"TELEGRAM MATNI:\n{copy.caption_tg[:3000]}",
                f"INSTAGRAM MATNI:\n{copy.caption_ig[:3000]}",
                f"CTA: {copy.cta}\nHASHTAGLAR: {' '.join(copy.hashtags)}",
                "Yuqoridagi postni tekshir va JSON qaytar: approved, score, issues, "
                "fixed_caption_tg, fixed_caption_ig, summary.",
            ]
        )
        return await self.ask_json(prompt, EditorOutput, system=system, temperature=0.25, max_tokens=2000)

    @staticmethod
    def _merge(local: EditorOutput, llm: EditorOutput, local_issues: list[EditorIssue]) -> EditorOutput:
        """Local rules win on severity; the LLM adds language-level findings."""
        merged_issues = list(local_issues)
        seen = {(i.field, i.problem[:40]) for i in merged_issues}
        for issue in llm.issues:
            key = (issue.field, issue.problem[:40])
            if key not in seen:
                merged_issues.append(issue)
                seen.add(key)

        llm_score = min(10.0, max(0.0, llm.score))
        local_score = local.score
        return EditorOutput(
            approved=llm.approved and local.approved,
            score=round(min(local_score, llm_score if llm_score else local_score), 2),
            issues=merged_issues,
            fixed_caption_tg=llm.fixed_caption_tg,
            fixed_caption_ig=llm.fixed_caption_ig,
            summary=llm.summary,
        )

    @staticmethod
    def _apply_fixes(copy: CopyOutput, report: EditorOutput) -> CopyOutput:
        """Adopt the editor's rewrite only when it is plausibly complete."""
        if report.fixed_caption_tg and word_count(report.fixed_caption_tg) >= MIN_CAPTION_WORDS:
            copy.caption_tg = truncate_caption(
                normalize_apostrophes(report.fixed_caption_tg), TG_MESSAGE_LIMIT
            )
        if report.fixed_caption_ig and word_count(report.fixed_caption_ig) >= MIN_CAPTION_WORDS:
            copy.caption_ig = truncate_caption(
                normalize_apostrophes(report.fixed_caption_ig), IG_CAPTION_LIMIT
            )
        return copy

    @staticmethod
    def _tidy_contacts(copy: CopyOutput, kb: KnowledgeBase | None) -> CopyOutput:
        """The rewrite reintroduces the phone the copywriter already placed."""
        phone = (kb.phone or "") if kb else ""
        if phone:
            copy.caption_tg = dedupe_phone(copy.caption_tg, phone)
            copy.caption_ig = dedupe_phone(copy.caption_ig, phone)
        return copy
