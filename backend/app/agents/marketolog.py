"""MarketologAgent — decides the week's commercial angle for the strategist.

The strategist answers *what goes out and when*. Nothing answered *why this
week, to whom, against which objection* — so every week's plan reads like the
last one with different topics. This agent makes that call once per plan and
hands the strategist a brief.

It writes no posts and picks no dates. Its whole output is a short brief that
reaches the strategist through ``StrategyRequest.extra_instructions``, which
means the strategist itself needs no changes: it already treats that field as
instructions to honour.

Runs once a week per business, so it is worth the pro model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent, knowledge_context
from app.agents.prompts import MARKETOLOG_SYSTEM
from app.core.logging import get_logger
from app.models.business import Business
from app.models.knowledge_base import KnowledgeBase
from app.utils.json_tools import compact_json

log = get_logger(__name__)


class MarketingBrief(BaseModel):
    """The commercial frame for one planning horizon."""

    segment: str = Field(default="", description="Shu hafta kimga gapiramiz")
    offer: str = Field(default="", description="Qaysi mavjud taklif oldinga chiqadi")
    angle: str = Field(default="", description="Nega aynan hozir")
    objection: str = Field(default="", description="Segmentning eng kuchli e'tirozi")
    proof: str = Field(default="", description="E'tirozni sindiradigan dalil")
    avoid: list[str] = Field(default_factory=list, description="Shu hafta tegilmaydigan mavzular")
    gaps: list[str] = Field(default_factory=list, description="Yetishmayotgan ma'lumot")

    @property
    def is_usable(self) -> bool:
        """A brief with no segment and no offer says nothing worth passing on."""
        return bool(self.segment.strip() or self.offer.strip())

    def as_instructions(self) -> str:
        """Render the brief as the instruction block the strategist reads.

        Empty fields are dropped rather than sent as blank labels — a heading
        with nothing under it reads to the model as a field it should invent.
        """
        lines = [
            ("SEGMENT", self.segment),
            ("TAKLIF", self.offer),
            ("BURCHAK", self.angle),
            ("E'TIROZ", self.objection),
            ("DALIL", self.proof),
        ]
        body = [f"- {label}: {value.strip()}" for label, value in lines if value.strip()]
        if self.avoid:
            body.append(f"- TEGMA: {', '.join(a.strip() for a in self.avoid if a.strip())}")
        if not body:
            return ""
        return "MARKETOLOG BRIEFI (shu haftaning tijorat burchagi):\n" + "\n".join(body)


@dataclass(slots=True)
class MarketingRequest:
    business: Business
    knowledge: KnowledgeBase | None
    horizon_days: int = 7
    posts_count: int = 10
    #: `ContentItemRepository.recent_performance` output — empty for a business
    #: with nothing published yet, which is the honest state to plan from.
    performance: dict[str, Any] = field(default_factory=dict)
    extra_instructions: str = ""


class MarketologAgent(BaseAgent):
    name = "marketolog"
    use_pro_model = True

    async def run(self, request: MarketingRequest) -> MarketingBrief:
        system = await self.system_prompt(MARKETOLOG_SYSTEM, business_id=request.business.id)
        prompt = "\n\n".join(
            filter(
                None,
                [
                    knowledge_context(request.business, request.knowledge),
                    self._performance_block(request.performance),
                    f"REJA: {request.horizon_days} kun, {request.posts_count} ta post.",
                    f"EGA QO'SHIMCHASI: {request.extra_instructions}" if request.extra_instructions else "",
                    "Shu haftaning tijorat briefini JSON qaytar.",
                ],
            )
        )

        try:
            brief = await self.ask_json(
                prompt, MarketingBrief, system=system, temperature=0.6, max_tokens=900
            )
        except Exception as exc:
            # The strategist planned without a brief before this agent existed;
            # an empty brief puts it back in exactly that state.
            log.warning("marketolog_failed_planning_without_brief", error=str(exc)[:200])
            return MarketingBrief()

        if brief.gaps:
            log.info("marketolog_gaps", business=str(request.business.id), gaps=brief.gaps[:5])
        return brief

    @staticmethod
    def _performance_block(performance: dict[str, Any]) -> str:
        """Last two months as the marketer should see them.

        Reaction totals are only meaningful next to how many posts carried
        them, so both are shown; a pillar with one measured post is not
        evidence and the prompt is told to treat it that way.
        """
        if not performance or not performance.get("published"):
            return "NATIJA: hali e'lon qilingan post yo'q — birinchi haftani bilim bazasiga tayanib rejalashtir."

        by_pillar = performance.get("by_pillar") or {}
        rows = []
        for pillar, bucket in by_pillar.items():
            posts = int(bucket.get("posts") or 0)
            measured = int(bucket.get("measured") or 0)
            average = bucket.get("avg_reactions")
            if average is None:
                rows.append(f"- {pillar}: {posts} post, reaksiya o'lchanmagan")
            else:
                rows.append(f"- {pillar}: {posts} post, {measured} tasi o'lchangan, o'rtacha {average} reaksiya")

        topics = performance.get("recent_topics") or []
        parts = [f"NATIJA (so'nggi 60 kun, {performance.get('published')} post):"]
        parts.extend(rows or ["- pillar bo'yicha ma'lumot yo'q"])
        if topics:
            parts.append("SO'NGGI MAVZULAR (takrorlama): " + compact_json(topics[:24]))
        return "\n".join(parts)
