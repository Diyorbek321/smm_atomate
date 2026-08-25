"""AnalystAgent — reads what the system produced and what it earned.

Two sources feed this, and they are not equally strong:

* **Production** — quality scores, rewrite rate, rejections, publish failures.
  Complete and reliable: every item carries it.
* **Reaction** — Telegram reaction totals, recorded by
  ``app.bot.handlers.reactions``. Partial by nature: the Bot API exposes no view
  count, Instagram contributes nothing, and a post only appears here once
  somebody reacts to it.

So the agent is told how many posts were actually measured and instructed to
scale its confidence to that, rather than reporting an average over four posts
as if it were a trend. The output feeds the marketolog's next brief.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.agents.prompts import ANALYST_SYSTEM
from app.core.logging import get_logger
from app.models.business import Business
from app.models.content_item import ContentItem
from app.models.enums import ContentItemStatus
from app.utils.json_tools import compact_json

log = get_logger(__name__)

#: Below this many posts, any pillar comparison is noise rather than signal.
MIN_POSTS_FOR_SIGNAL = 5


class Finding(BaseModel):
    """One observation, with the numbers that produced it."""

    text: str = Field(default="", description="Raqam bilan yozilgan kuzatuv")
    evidence: str = Field(default="", description="Qaysi raqamga tayanadi")


class AnalysisReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    note: str = Field(default="", description="Ma'lumot yetarli bo'lmasa shu yerda ayt")

    def as_instructions(self) -> str:
        """Render the recommendations for the marketolog's next brief."""
        usable = [r.strip() for r in self.recommendations if r.strip()]
        if not usable:
            return ""
        listed = "\n".join(f"- {r}" for r in usable)
        return f"ANALITIK TAVSIYALARI (o'tgan davr natijasidan):\n{listed}"


@dataclass(slots=True)
class AnalysisRequest:
    business: Business
    #: `ContentItemRepository.recent_performance` output.
    performance: dict[str, Any] = field(default_factory=dict)
    #: `production_stats` output.
    production: dict[str, Any] = field(default_factory=dict)
    days: int = 30


def production_stats(items: list[ContentItem]) -> dict[str, Any]:
    """Everything measurable about how the pipeline behaved, from the items.

    Deliberately a pure function over rows already loaded: it is the part worth
    unit-testing, and it keeps the agent free of database access.
    """
    if not items:
        return {"total": 0}

    scores = [i.quality_score for i in items if isinstance(i.quality_score, int | float) and i.quality_score > 0]
    rejected = [i for i in items if i.status == ContentItemStatus.REJECTED]
    failed = [i for i in items if i.status == ContentItemStatus.FAILED]
    regenerated = [i for i in items if (i.regeneration_count or 0) > 0]

    # An item can fail without anything being written to `last_error`; those
    # still belong in the tally, under a label that says so.
    failure_reasons = Counter((i.last_error or "sabab yozilmagan")[:80] for i in failed)

    return {
        "total": len(items),
        "by_pillar": dict(Counter(i.pillar.value for i in items)),
        "by_type": dict(Counter(i.content_type.value for i in items)),
        "by_status": dict(Counter(i.status.value for i in items)),
        "avg_quality": round(sum(scores) / len(scores), 2) if scores else None,
        "low_quality": sum(1 for s in scores if s < 7.0),
        "measured_quality": len(scores),
        "regenerated": len(regenerated),
        "rejected": len(rejected),
        "failed": len(failed),
        "failure_reasons": dict(failure_reasons.most_common(5)),
    }


class AnalystAgent(BaseAgent):
    name = "analyst"
    use_pro_model = True

    async def run(self, request: AnalysisRequest) -> AnalysisReport:
        produced = int(request.production.get("total") or 0)
        if produced == 0:
            return AnalysisReport(
                confidence=0.0,
                note="Tahlil qilinadigan post yo'q — bu davrda hech narsa yaratilmagan.",
            )

        system = await self.system_prompt(ANALYST_SYSTEM, business_id=request.business.id)
        prompt = "\n\n".join(
            filter(
                None,
                [
                    f"BIZNES: {request.business.name}",
                    f"DAVR: so'nggi {request.days} kun",
                    f"ISHLAB CHIQARISH:\n{compact_json(request.production)}",
                    self._reaction_block(request.performance),
                    "Tahlilni JSON qaytar.",
                ],
            )
        )

        try:
            report = await self.ask_json(
                prompt, AnalysisReport, system=system, temperature=0.3, max_tokens=1200
            )
        except Exception as exc:
            log.warning("analyst_failed", business=str(request.business.id), error=str(exc)[:200])
            return AnalysisReport(confidence=0.0, note="Tahlil bajarilmadi.")

        return self._cap_confidence(report, request)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _reaction_block(performance: dict[str, Any]) -> str:
        """Reaction data, always stated together with how much of it is real."""
        published = int((performance or {}).get("published") or 0)
        if not published:
            return "REAKSIYA: hali e'lon qilingan post yo'q."

        by_pillar = performance.get("by_pillar") or {}
        measured = sum(int(b.get("measured") or 0) for b in by_pillar.values())
        if measured == 0:
            return (
                f"REAKSIYA: {published} post e'lon qilingan, lekin birortasida reaksiya "
                "o'lchanmagan. Reaksiya bo'yicha xulosa CHIQARMA."
            )

        rows = []
        for pillar, bucket in by_pillar.items():
            rows.append(
                f"- {pillar}: {int(bucket.get('posts') or 0)} post, "
                f"{int(bucket.get('measured') or 0)} tasi o'lchangan, "
                f"o'rtacha {bucket.get('avg_reactions')} reaksiya"
            )
        return (
            f"REAKSIYA ({published} post e'lon qilindi, {measured} tasida o'lchov bor):\n"
            + "\n".join(rows)
        )

    @staticmethod
    def _cap_confidence(report: AnalysisReport, request: AnalysisRequest) -> AnalysisReport:
        """Hold confidence down to what the sample size actually supports.

        The model is asked for this in the prompt and mostly complies, but a
        confident-sounding conclusion drawn from three posts is the one failure
        here that would actively mislead — so the ceiling is enforced in code.
        """
        produced = int(request.production.get("total") or 0)
        measured = sum(
            int(b.get("measured") or 0)
            for b in (request.performance.get("by_pillar") or {}).values()
        )

        ceiling = 1.0
        note = report.note
        if produced < MIN_POSTS_FOR_SIGNAL:
            ceiling = 0.4
            note = note or f"Faqat {produced} ta post — xulosalar dastlabki."
        if measured < MIN_POSTS_FOR_SIGNAL:
            ceiling = min(ceiling, 0.5)
            note = note or f"Reaksiya faqat {measured} ta postda o'lchangan."

        return AnalysisReport(
            findings=report.findings[:4],
            recommendations=[r.strip() for r in report.recommendations if r.strip()][:3],
            confidence=round(min(report.confidence, ceiling), 2),
            note=note,
        )
