"""StrategistAgent — turns the knowledge base into a dated content matrix."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.agents.base import BaseAgent, knowledge_context
from app.agents.prompts import STRATEGIST_SYSTEM
from app.core.logging import get_logger
from app.core.plans import pillar_content_types
from app.models.business import Business
from app.models.enums import (
    PILLAR_CONTENT_TYPES,
    PILLAR_DISTRIBUTION,
    ContentPillar,
    ContentType,
    Platform,
)
from app.models.knowledge_base import KnowledgeBase
from app.schemas.content import PlanSlot, StrategyOutput
from app.utils.json_tools import compact_json
from app.utils.similarity import DUPLICATE_THRESHOLD, similarity

log = get_logger(__name__)


def pillar_ratios_for(business: Business | None) -> dict[ContentPillar, float]:
    """Per-business mix from `settings.pillar_ratios`, else the default split.

    The owner can say e.g. "3 of 4 posts must inform, 1 sells" — that lives in
    the business settings, not in code.
    """
    raw = (business.settings or {}).get("pillar_ratios") if business is not None else None
    if not isinstance(raw, dict):
        return dict(PILLAR_DISTRIBUTION)

    ratios: dict[ContentPillar, float] = {}
    for key, value in raw.items():
        try:
            pillar = ContentPillar(str(key))
            share = float(value)
        except (TypeError, ValueError):
            continue
        if share > 0:
            ratios[pillar] = share

    total = sum(ratios.values())
    if not ratios or total <= 0:
        return dict(PILLAR_DISTRIBUTION)
    return {pillar: ratios.get(pillar, 0.0) / total for pillar in PILLAR_DISTRIBUTION}


def allocate_pillars(
    total: int, ratios: dict[ContentPillar, float] | None = None
) -> dict[ContentPillar, int]:
    """Split `total` posts across pillars using the largest-remainder method.

    Guarantees the counts sum exactly to `total` and that every pillar with a
    positive share gets at least one slot once there are enough posts.
    """
    shares = ratios or PILLAR_DISTRIBUTION
    if total <= 0:
        return {pillar: 0 for pillar in PILLAR_DISTRIBUTION}

    exact = {pillar: total * shares.get(pillar, 0.0) for pillar in PILLAR_DISTRIBUTION}
    counts = {pillar: int(value) for pillar, value in exact.items()}
    remainder = total - sum(counts.values())

    ranked = sorted(exact.items(), key=lambda kv: (kv[1] - int(kv[1]), shares.get(kv[0], 0.0)), reverse=True)
    for pillar, _ in ranked:
        if remainder <= 0:
            break
        counts[pillar] += 1
        remainder -= 1

    # With enough posts every active pillar must be represented; borrow from the biggest.
    active = [pillar for pillar in PILLAR_DISTRIBUTION if shares.get(pillar, 0.0) > 0]
    if total >= len(active):
        for pillar in active:
            if counts[pillar] == 0:
                donor = max(counts, key=lambda p: counts[p])
                if counts[donor] > 1:
                    counts[donor] -= 1
                    counts[pillar] = 1
    return counts


def default_content_type(
    pillar: ContentPillar,
    index: int,
    options_by_pillar: dict[ContentPillar, list[ContentType]] | None = None,
) -> ContentType:
    """Rotate through the content types allowed for a pillar on this tier."""
    options = (options_by_pillar or PILLAR_CONTENT_TYPES)[pillar]
    return options[index % len(options)]


@dataclass(slots=True)
class StrategyRequest:
    business: Business
    knowledge: KnowledgeBase | None
    starts_on: date
    horizon_days: int = 7
    posts_count: int = 10
    extra_instructions: str = ""
    #: What the last two months actually did — see
    #: :meth:`ContentItemRepository.recent_performance`. Carries the covered
    #: and rejected topic lists even when nothing has been published yet, which
    #: is exactly the account that needs them most.
    performance: dict[str, Any] = field(default_factory=dict)


def _performance_block(performance: dict[str, Any]) -> str:
    """Last two months, as the planner should see them.

    Two independent sections, because they answer to different evidence.
    *Numbers* need published posts: reactions are reported per pillar rather
    than per post, since one post going wide says little and a pillar
    consistently earning nothing says a lot.

    *Covered ground* needs no publishing at all, and gating it on the numbers
    was the bug that made every plan a copy of the last one. An account that
    reviews before publishing has almost nothing published, so the whole block
    used to come back empty — and the planner, with no memory of the topics it
    had proposed and had rejected days earlier, proposed them again.
    """
    if not performance:
        return ""

    lines: list[str] = []
    published = performance.get("published") or 0
    if published:
        lines.append(f"OXIRGI 60 KUN: {published} ta post chiqdi.")
        ranked = sorted(
            performance.get("by_pillar", {}).items(),
            key=lambda kv: (kv[1].get("avg_reactions") is None, -(kv[1].get("avg_reactions") or 0)),
        )
        for name, stats in ranked:
            average = stats.get("avg_reactions")
            measured = "o'lchanmagan" if average is None else f"o'rtacha {average} reaksiya"
            lines.append(f"  {name}: {int(stats['posts'])} post · {measured}")
        if len(ranked) > 1 and ranked[0][1].get("avg_reactions"):
            lines.append(
                f"Eng ko'p javob bergan ustun — {ranked[0][0]}. Ulushni o'zgartirma, "
                "lekin shu ustundagi mavzularni kuchliroq ishla."
            )

    topics = performance.get("recent_topics") or []
    if topics:
        lines.append(
            "ALLAQACHON YOZILGAN MAVZULAR — chiqqani ham, ko'rikda turgani ham, "
            "almashtirilgani ham. Bu ro'yxat yopiq: takrorlama, birortasini "
            "qayta yozma, yangi burchak top:"
        )
        lines.append("  " + " · ".join(topics[:16]))

    # Kept separate and stated harder than the covered list. A topic nobody
    # got round to is merely used up; one the owner read and turned down is an
    # instruction, and it is the signal this pipeline used to discard entirely.
    rejected = performance.get("rejected_topics") or []
    if rejected:
        lines.append(
            "EGA RAD ETGAN MAVZULAR (qat'iy taqiq — bu mavzularni boshqa burchakdan ham taklif qilma):"
        )
        lines.append("  " + " · ".join(rejected[:10]))
    return "\n".join(lines)


class StrategistAgent(BaseAgent):
    name = "strategist"
    use_pro_model = True

    async def run(self, request: StrategyRequest) -> StrategyOutput:
        allocation = allocate_pillars(request.posts_count, pillar_ratios_for(request.business))
        blueprint = self._blueprint(allocation, request)

        system = await self.system_prompt(STRATEGIST_SYSTEM, business_id=request.business.id)
        prompt = self._build_prompt(request, allocation, blueprint)

        try:
            strategy = await self.ask_json(
                prompt,
                StrategyOutput,
                system=system,
                temperature=0.85,
                max_tokens=3500,
            )
        except Exception as exc:
            log.error("strategist_failed_using_blueprint", business=str(request.business.id), error=str(exc)[:300])
            return StrategyOutput(
                theme="Avtomatik reja",
                objectives=["Doimiy kontent oqimini saqlash"],
                slots=blueprint,
                notes=f"fallback: {str(exc)[:200]}",
            )

        strategy.slots = self._enforce(strategy.slots, allocation, blueprint, request)
        log.info(
            "strategy_ready",
            business=str(request.business.id),
            slots=len(strategy.slots),
            allocation={str(k): v for k, v in allocation.items()},
        )
        return strategy

    # ------------------------------------------------------------------ #
    def _blueprint(self, allocation: dict[ContentPillar, int], request: StrategyRequest) -> list[PlanSlot]:
        """Deterministic skeleton — also the fallback when the LLM misbehaves."""
        hours = request.business.posting_hours
        allowed_types = pillar_content_types(request.business.capabilities)
        slots: list[PlanSlot] = []
        # Interleave pillars so the week never shows three sales posts in a row.
        interleaved: list[ContentPillar] = []
        pools = {pillar: [pillar] * count for pillar, count in allocation.items()}
        while any(pools.values()):
            for pillar in PILLAR_DISTRIBUTION:
                if pools[pillar]:
                    interleaved.append(pools[pillar].pop())

        per_pillar_index: dict[ContentPillar, int] = {p: 0 for p in PILLAR_DISTRIBUTION}
        for index, pillar in enumerate(interleaved):
            content_type = default_content_type(pillar, per_pillar_index[pillar], allowed_types)
            per_pillar_index[pillar] += 1
            slots.append(
                PlanSlot(
                    day_offset=index % max(1, request.horizon_days),
                    hour=hours[index % len(hours)],
                    pillar=pillar,
                    content_type=content_type,
                    topic=f"{pillar.value} kontenti #{per_pillar_index[pillar]}",
                    angle="",
                    goal="",
                    platform=Platform.TELEGRAM if content_type == ContentType.TELEGRAM_QUIZ else Platform.BOTH,
                )
            )
        return slots

    def _build_prompt(
        self,
        request: StrategyRequest,
        allocation: dict[ContentPillar, int],
        blueprint: list[PlanSlot],
    ) -> str:
        kb = request.knowledge
        allowed = {
            pillar.value: [t.value for t in types]
            for pillar, types in pillar_content_types(request.business.capabilities).items()
        }
        skeleton = [
            {"day_offset": s.day_offset, "hour": s.hour, "pillar": s.pillar.value}
            for s in blueprint
        ]
        return "\n\n".join(
            filter(
                None,
                [
                    knowledge_context(request.business, kb),
                    f"REJA DAVRI: {request.starts_on.isoformat()} dan boshlab {request.horizon_days} kun.",
                    f"JAMI POSTLAR: {request.posts_count}",
                    "USTUNLAR BO'YICHA ANIQ SON (o'zgartirma):\n"
                    + compact_json({p.value: c for p, c in allocation.items()}),
                    "RUXSAT ETILGAN content_type LAR:\n" + compact_json(allowed),
                    "VAQT SKELETI (day_offset/hour/pillar juftliklarini shu ko'rinishda saqla):\n"
                    + compact_json(skeleton),
                    (
                        "TAQIQLANGAN MAVZULAR: " + compact_json(kb.banned_topics)
                        if kb and kb.banned_topics
                        else ""
                    ),
                    _performance_block(request.performance),
                    (f"QO'SHIMCHA KO'RSATMA: {request.extra_instructions}" if request.extra_instructions else ""),
                    (
                        "Natijani JSON qaytar: theme, objectives (2-4 ta), slots (har biri day_offset, "
                        "hour, pillar, content_type, topic, angle, goal, platform), notes."
                    ),
                ],
            )
        )

    def _enforce(
        self,
        slots: list[PlanSlot],
        allocation: dict[ContentPillar, int],
        blueprint: list[PlanSlot],
        request: StrategyRequest,
    ) -> list[PlanSlot]:
        """Repair LLM output: exact pillar counts, valid types, unique topics."""
        target_total = sum(allocation.values())
        buckets: dict[ContentPillar, list[PlanSlot]] = {p: [] for p in PILLAR_DISTRIBUTION}

        allowed_types = pillar_content_types(request.business.capabilities)
        # Exact-match dedup let "STANDARD tarif tarkibi" and "STANDARD tarif
        # tarkibi va imkoniyatlari" both through, which is two posts about the
        # same thing in the same week. The overlap measure is what the editor
        # already uses to judge a repeat; the plan should apply it first.
        accepted_topics: list[str] = []
        for slot in slots:
            topic = slot.topic.strip()
            if not topic or any(
                similarity(topic, seen) >= DUPLICATE_THRESHOLD for seen in accepted_topics
            ):
                continue
            if slot.content_type not in allowed_types[slot.pillar]:
                slot.content_type = default_content_type(
                    slot.pillar, len(buckets[slot.pillar]), allowed_types
                )
            if slot.content_type == ContentType.TELEGRAM_QUIZ:
                slot.platform = Platform.TELEGRAM
            slot.day_offset = min(max(0, slot.day_offset), max(0, request.horizon_days - 1))
            slot.hour = min(23, max(0, slot.hour))
            accepted_topics.append(topic)
            buckets[slot.pillar].append(slot)

        final: list[PlanSlot] = []
        for pillar, wanted in allocation.items():
            available = buckets[pillar][:wanted]
            missing = wanted - len(available)
            if missing > 0:
                spares = [s for s in blueprint if s.pillar == pillar][:missing]
                available.extend(spares[:missing])
            final.extend(available[:wanted])

        # Re-spread across the horizon using the deterministic skeleton timing.
        final.sort(key=lambda s: (s.day_offset, s.hour))
        for index, slot in enumerate(final):
            reference = blueprint[index] if index < len(blueprint) else blueprint[-1]
            slot.day_offset = reference.day_offset
            slot.hour = reference.hour

        return final[:target_total]


async def build_strategy(
    session: object,
    business: Business,
    knowledge: KnowledgeBase | None,
    *,
    starts_on: date,
    horizon_days: int,
    posts_count: int,
    extra_instructions: str = "",
    business_id: uuid.UUID | None = None,
) -> StrategyOutput:
    """Convenience wrapper used by the orchestrator."""
    agent = StrategistAgent(session=session)  # type: ignore[arg-type]
    return await agent.run(
        StrategyRequest(
            business=business,
            knowledge=knowledge,
            starts_on=starts_on,
            horizon_days=horizon_days,
            posts_count=posts_count,
            extra_instructions=extra_instructions,
        )
    )
