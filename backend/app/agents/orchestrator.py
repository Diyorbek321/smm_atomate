"""ContentPipeline — wires Strategist → Copywriter → Visual → Editor together."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analyst import AnalysisRequest, AnalystAgent, production_stats
from app.agents.base import AgentUsage
from app.agents.copywriter import CopyRequest, CopywriterAgent
from app.agents.designer import DesignerAgent, DesignRequest
from app.agents.editor import EditorAgent, EditorRequest, EditorResult
from app.agents.hook import HookAgent, HookRequest
from app.agents.marketolog import MarketingRequest, MarketologAgent
from app.agents.strategist import StrategistAgent, StrategyRequest
from app.agents.visual import VisualAgent, VisualRequest
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.business import Business
from app.models.content_item import ContentItem
from app.models.content_plan import ContentPlan
from app.models.enums import (
    ContentItemStatus,
    ContentPillar,
    ContentPlanStatus,
    ContentType,
    Platform,
)
from app.models.knowledge_base import KnowledgeBase
from app.repositories.business import BusinessRepository, KnowledgeBaseRepository
from app.repositories.content import ContentItemRepository, ContentPlanRepository
from app.schemas.content import CopyOutput, PlanSlot, StrategyOutput
from app.utils.dates import iso_week, next_monday, slot_to_datetime, utcnow

log = get_logger(__name__)

#: How many items are generated concurrently (each is several LLM calls).
#: Configurable because providers meter tokens per minute.
#: An item below this editor score is rewritten once before giving up.
REWRITE_THRESHOLD = 7.0
MAX_REWRITES = 1

#: (slot, copy, review, visual, error) — one generated slot, error set on failure.
SlotOutcome = tuple[
    "PlanSlot", "CopyOutput | None", "EditorResult | None", object | None, str | None
]


def _replace_opening(caption: str, old_hook: str, new_hook: str) -> str:
    """Swap the caption's first line, but only when it is the hook.

    The copywriter usually opens the caption with the same sentence it returns
    in ``hook`` — usually, not always. When the first line is something else,
    the caption is left exactly as the editor approved it and only the ``hook``
    field changes; a hook stitched onto an unrelated opening reads worse than
    the one it replaced.
    """
    if not caption.strip() or not old_hook.strip() or not new_hook.strip():
        return caption

    def flatten(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())

    head, separator, tail = caption.partition("\n")
    if flatten(head) != flatten(old_hook):
        return caption
    return f"{new_hook}{separator}{tail}"


@dataclass(slots=True)
class PipelineResult:
    plan: ContentPlan | None = None
    items: list[ContentItem] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    usage: AgentUsage = field(default_factory=AgentUsage)

    @property
    def item_ids(self) -> list[uuid.UUID]:
        return [item.id for item in self.items]


class ContentPipeline:
    """Orchestrates the multi-agent generation flow for one business."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.usage = AgentUsage()
        self.businesses = BusinessRepository(session)
        self.knowledge_repo = KnowledgeBaseRepository(session)
        self.plans = ContentPlanRepository(session)
        self.items = ContentItemRepository(session)
        #: Filled once per orchestrator, not once per slot — eight posts in a
        #: week would otherwise mean eight identical queries.
        self._recent_headlines: dict[uuid.UUID, list[str]] = {}

    # ------------------------------------------------------------------ #
    # Full plan generation
    # ------------------------------------------------------------------ #
    async def generate_plan(
        self,
        business_id: uuid.UUID,
        *,
        starts_on: date | None = None,
        horizon_days: int = 7,
        posts_count: int | None = None,
        extra_instructions: str = "",
    ) -> PipelineResult:
        business = await self.businesses.get_full(business_id)
        if business is None:
            raise NotFoundError(f"Business {business_id} not found")

        knowledge = business.knowledge_base or await self.knowledge_repo.get_or_create(business_id)
        start = starts_on or next_monday()
        total = posts_count or business.posts_per_week
        if horizon_days != 7:
            total = max(3, round(total * horizon_days / 7))

        plan = await self._prepare_plan(business, start, horizon_days, total)
        result = PipelineResult(plan=plan)

        # Fetched once and shared: the marketolog and the strategist plan from
        # the same two months, and this is the same query either way.
        performance = await ContentItemRepository(self.session).recent_performance(business.id)
        instructions = await self._marketing_brief(
            business, knowledge, horizon_days, total, performance, extra_instructions
        )

        strategy = await self._strategy(
            business, knowledge, start, horizon_days, total, instructions, performance
        )
        plan.title = strategy.theme or plan.title
        plan.strategy = strategy.model_dump(mode="json")
        plan.notes = strategy.notes

        items, failures = await self._generate_items(business, knowledge, plan, strategy, start)
        result.items = items
        result.failures = failures

        plan.status = ContentPlanStatus.PENDING_REVIEW if items else ContentPlanStatus.DRAFT
        if failures:
            plan.generation_error = "; ".join(failures)[:2000]
        await self.session.flush()

        result.usage = self.usage
        log.info(
            "plan_generated",
            business=str(business_id),
            plan=str(plan.id),
            items=len(items),
            failures=len(failures),
            cost_usd=self.usage.cost_usd,
        )
        return result

    async def _prepare_plan(
        self, business: Business, start: date, horizon_days: int, total: int
    ) -> ContentPlan:
        """Reuse the week's plan when regenerating, otherwise create a new one."""
        from datetime import timedelta

        year, week = iso_week(start)
        plan = await self.plans.find_for_week(business.id, start)
        if plan is not None:
            # Regenerating a week supersedes whatever was never approved;
            # approved and published items are left untouched.
            for existing in list(plan.items):
                if existing.status in (ContentItemStatus.PENDING_REVIEW, ContentItemStatus.DRAFT):
                    existing.status = ContentItemStatus.REJECTED
                    existing.review_notes = "qayta yaratilgani uchun almashtirildi"
            plan.status = ContentPlanStatus.GENERATING
            plan.generation_error = None
            await self.session.flush()
            return plan

        plan = ContentPlan(
            business_id=business.id,
            title=f"{business.name} — {year}-W{week:02d}",
            year=year,
            week_number=week,
            month_number=start.month,
            starts_on=start,
            ends_on=start + timedelta(days=max(0, horizon_days - 1)),
            status=ContentPlanStatus.GENERATING,
            strategy={"requested_posts": total},
        )
        # Mark the collection as loaded while the row is still pending, so
        # appending items later never triggers a lazy SELECT outside greenlet.
        plan.items = []
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def _marketing_brief(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        horizon_days: int,
        total: int,
        performance: dict[str, Any],
        extra_instructions: str,
    ) -> str:
        """Prepend the week's commercial angle to whatever the owner asked for.

        The strategist reads ``extra_instructions`` already, so the brief needs
        no change on its side. When the agent is off or returns nothing usable,
        the instructions pass through untouched and planning behaves exactly as
        it did before this existed.
        """
        if not settings.use_marketolog_agent:
            return extra_instructions

        # The analyst reads last month and writes recommendations; the
        # marketolog is the only thing that acts on them, so it runs here
        # rather than on its own schedule.
        briefed = "\n\n".join(
            filter(None, [await self._analysis(business, performance), extra_instructions])
        )

        agent = MarketologAgent(session=self.session, usage=self.usage)
        brief = await agent.run(
            MarketingRequest(
                business=business,
                knowledge=knowledge,
                horizon_days=horizon_days,
                posts_count=total,
                performance=performance,
                extra_instructions=briefed,
            )
        )
        if not brief.is_usable:
            return extra_instructions

        log.info("marketing_brief", business=str(business.id), segment=brief.segment[:60])
        return "\n\n".join(filter(None, [brief.as_instructions(), extra_instructions]))

    async def _analysis(self, business: Business, performance: dict[str, Any]) -> str:
        """Last month as the analyst read it, rendered for the marketolog.

        Failure here is not worth failing a plan over: an empty string puts the
        marketolog back to briefing from the performance numbers alone, which
        is what it did before this agent existed.
        """
        if not settings.use_analyst_agent:
            return ""

        items = list(
            await ContentItemRepository(self.session).produced_between(
                business.id, days=settings.analyst_window_days
            )
        )
        production = production_stats(items)
        if not production.get("total"):
            return ""

        agent = AnalystAgent(session=self.session, usage=self.usage)
        report = await agent.run(
            AnalysisRequest(
                business=business,
                performance=performance,
                production=production,
                days=settings.analyst_window_days,
            )
        )
        instructions = report.as_instructions()
        if instructions:
            log.info(
                "analysis_briefed",
                business=str(business.id),
                confidence=report.confidence,
                recommendations=len(report.recommendations),
            )
        return instructions

    async def _strategy(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        start: date,
        horizon_days: int,
        total: int,
        extra_instructions: str,
        performance: dict[str, Any],
    ) -> StrategyOutput:
        agent = StrategistAgent(session=self.session, usage=self.usage)
        return await agent.run(
            StrategyRequest(
                business=business,
                knowledge=knowledge,
                starts_on=start,
                horizon_days=horizon_days,
                posts_count=total,
                extra_instructions=extra_instructions,
                # Planning without this is planning blind: the strategist could
                # not previously see which pillar earned a response, or what it
                # had already covered last month.
                performance=performance,
            )
        )

    async def _generate_items(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        plan: ContentPlan,
        strategy: StrategyOutput,
        start: date,
    ) -> tuple[list[ContentItem], list[str]]:
        """Generate every slot with bounded concurrency, keeping partial results."""
        semaphore = asyncio.Semaphore(max(1, settings.generation_concurrency))

        async def _one(slot: PlanSlot) -> SlotOutcome:
            async with semaphore:
                try:
                    copy, review, visual = await self._compose(business, knowledge, slot)
                    return slot, copy, review, visual, None
                except Exception as exc:
                    log.error("slot_generation_failed", topic=slot.topic[:80], error=str(exc)[:300])
                    return slot, None, None, None, f"{slot.topic[:60]}: {str(exc)[:160]}"

        outcomes = await asyncio.gather(*(_one(slot) for slot in strategy.slots))

        items: list[ContentItem] = []
        failures: list[str] = []
        for slot, copy, review, visual, error in outcomes:
            if error or copy is None:
                failures.append(error or "unknown error")
                continue
            item = self._build_item(business, plan, slot, copy, review, visual, start)
            # Append through the relationship so callers (the review card, the
            # bot summary) see the items without another round trip.
            plan.items.append(item)
            items.append(item)

        await self.session.flush()
        return items, failures

    async def _recent_history(self, business: Business) -> list[str]:
        """Last month's headlines for this business, fetched at most once."""
        cached = self._recent_headlines.get(business.id)
        if cached is None:
            try:
                cached = await self.items.recent_headlines(business.id)
            except Exception as exc:                     # history is a nicety
                log.warning("recent_headlines_failed", error=str(exc)[:200])
                cached = []
            self._recent_headlines[business.id] = cached
        return cached

    # ------------------------------------------------------------------ #
    # Single item generation
    # ------------------------------------------------------------------ #
    async def _compose(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        slot: PlanSlot,
        *,
        extra_instructions: str = "",
        previous_caption: str = "",
        render_image: bool = True,
    ) -> tuple[CopyOutput, EditorResult, object]:
        copywriter = CopywriterAgent(session=self.session, usage=self.usage)
        editor = EditorAgent(session=self.session, usage=self.usage)

        copy_request = CopyRequest(
            business=business,
            knowledge=knowledge,
            content_type=slot.content_type,
            pillar=slot.pillar,
            topic=slot.topic,
            angle=slot.angle,
            goal=slot.goal,
            extra_instructions=extra_instructions,
            previous_caption=previous_caption,
        )
        copy = await copywriter.run(copy_request)

        history = await self._recent_history(business)
        review = await editor.run(
            EditorRequest(
                business=business,
                knowledge=knowledge,
                copy=copy,
                content_type=slot.content_type,
                topic=slot.topic,
                recent_headlines=history,
            )
        )

        # Self-reflection loop: one targeted rewrite when the editor is unhappy.
        rewrites = 0
        while (not review.approved or review.score < REWRITE_THRESHOLD) and rewrites < MAX_REWRITES:
            rewrites += 1
            notes = "; ".join(
                f"{issue.field}: {issue.problem} → {issue.suggestion}".strip(" →")
                for issue in review.issues
                if issue.severity in ("critical", "major")
            )[:1200]
            log.info("rewrite_triggered", topic=slot.topic[:60], score=review.score, attempt=rewrites)
            copy_request.extra_instructions = (
                f"{extra_instructions}\nMUHARRIR IZOHI (albatta tuzat): {notes}".strip()
            )
            copy_request.previous_caption = review.copy.caption_tg
            copy = await copywriter.run(copy_request)
            review = await editor.run(
                EditorRequest(
                    business=business,
                    knowledge=knowledge,
                    copy=copy,
                    content_type=slot.content_type,
                    topic=slot.topic,
                    recent_headlines=history,
                )
            )

        copy = review.copy
        if settings.use_hook_agent:
            copy = await self._sharpen_hook(business, knowledge, slot, copy, editor, history)

        design = None
        if settings.use_designer_agent:
            designer = DesignerAgent(session=self.session, usage=self.usage)
            design = await designer.run(
                DesignRequest(
                    business=business,
                    knowledge=knowledge,
                    content_type=slot.content_type,
                    pillar=slot.pillar,
                    topic=slot.topic,
                    headline=copy.headline,
                    hook=copy.hook,
                    caption=copy.caption_tg,
                    cta=copy.cta,
                )
            )

        visual_agent = VisualAgent(session=self.session, usage=self.usage)
        visual = await visual_agent.run(
            VisualRequest(
                business=business,
                knowledge=knowledge,
                content_type=slot.content_type,
                pillar=slot.pillar,
                topic=slot.topic,
                headline=copy.headline,
                hook=copy.hook,
                cta=copy.cta,
                slides=copy.slides,
                generate_photo=render_image,
                design=design,
            )
        )
        return copy, review, visual

    async def _sharpen_hook(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        slot: PlanSlot,
        copy: CopyOutput,
        editor: EditorAgent,
        history: list[str],
    ) -> CopyOutput:
        """Rewrite the opening line of a caption the editor has already passed.

        Running after approval keeps the rewrite loop cheap, but it means the
        new line has never been checked. So the candidate goes back through the
        editor's *local* rules — no LLM call — and is dropped if it introduces a
        critical problem the approved copy did not have. A hook is never worth
        shipping a banned word for.
        """
        agent = HookAgent(session=self.session, usage=self.usage)
        result = await agent.run(
            HookRequest(
                business=business,
                knowledge=knowledge,
                content_type=slot.content_type,
                pillar=slot.pillar,
                topic=slot.topic,
                caption=copy.caption_tg,
                current_hook=copy.hook,
            )
        )
        if not result.changed:
            return copy

        candidate = copy.model_copy(
            update={
                "hook": result.hook,
                "caption_tg": _replace_opening(copy.caption_tg, copy.hook, result.hook),
                "caption_ig": _replace_opening(copy.caption_ig, copy.hook, result.hook),
            }
        )

        def critical_problems(subject: CopyOutput) -> set[str]:
            issues = editor.static_checks(
                EditorRequest(
                    business=business,
                    knowledge=knowledge,
                    copy=subject,
                    content_type=slot.content_type,
                    topic=slot.topic,
                    deep_check=False,
                    recent_headlines=history,
                )
            )
            return {issue.problem for issue in issues if issue.severity == "critical"}

        # Only *new* problems disqualify the hook. The approved copy may already
        # trip a rule the editor's LLM pass forgave; holding the hook to a higher
        # bar than the post it belongs to would reject every rewrite.
        before = critical_problems(copy)
        after = critical_problems(candidate)
        if after - before:
            log.info("hook_rejected_by_rules", topic=slot.topic[:60], issues=sorted(after - before)[:2])
            return copy

        log.info("hook_sharpened", topic=slot.topic[:60], hook=result.hook[:60])
        return candidate

    def _build_item(
        self,
        business: Business,
        plan: ContentPlan | None,
        slot: PlanSlot,
        copy: CopyOutput,
        review: EditorResult | None,
        visual: object | None,
        start: date,
        scheduled_at: datetime | None = None,
    ) -> ContentItem:
        when = scheduled_at or slot_to_datetime(start, slot.day_offset, slot.hour, business.timezone)
        auto_approve = business.auto_approve or settings.auto_approve
        status = ContentItemStatus.APPROVED if auto_approve else ContentItemStatus.PENDING_REVIEW

        item = ContentItem(
            business_id=business.id,
            content_plan_id=plan.id if plan else None,
            content_type=slot.content_type,
            pillar=slot.pillar,
            platform=slot.platform,
            topic=slot.topic,
            headline=copy.headline[:300],
            hook=copy.hook[:300],
            cta=copy.cta[:300],
            caption_tg=copy.caption_tg,
            caption_ig=copy.caption_ig,
            hashtags=copy.hashtags,
            options=copy.quiz or {},
            script=copy.script or {},
            scheduled_at=when,
            status=status,
        )
        self._apply_visual(item, visual, copy)
        if review is not None:
            item.quality_score = review.score
            item.editor_report = review.report.model_dump(mode="json")
        item.ai_meta = self.usage.as_dict()
        return item

    @staticmethod
    def _apply_visual(item: ContentItem, visual: object | None, copy: CopyOutput) -> None:
        if visual is None:
            item.carousel_slides = copy.slides
            return
        item.image_url = getattr(visual, "image_url", None)
        item.image_prompt = getattr(visual, "image_prompt", None)
        item.video_url = getattr(visual, "video_url", None)
        slides = getattr(visual, "slides", None) or copy.slides
        item.carousel_slides = slides
        warnings = getattr(visual, "warnings", None)
        if warnings:
            item.editor_report = {**(item.editor_report or {}), "visual_warnings": warnings}

    # ------------------------------------------------------------------ #
    # Ad-hoc single item
    # ------------------------------------------------------------------ #
    async def generate_single(
        self,
        business_id: uuid.UUID,
        *,
        content_type: ContentType = ContentType.FEED_POST,
        pillar: ContentPillar = ContentPillar.SALES,
        topic: str = "",
        platform: Platform = Platform.BOTH,
        scheduled_at: datetime | None = None,
        extra_instructions: str = "",
        render_image: bool = True,
        plan: ContentPlan | None = None,
    ) -> ContentItem:
        business = await self.businesses.get_full(business_id)
        if business is None:
            raise NotFoundError(f"Business {business_id} not found")
        knowledge = business.knowledge_base or await self.knowledge_repo.get_or_create(business_id)

        if content_type == ContentType.TELEGRAM_QUIZ:
            platform = Platform.TELEGRAM

        slot = PlanSlot(
            day_offset=0,
            hour=(scheduled_at or utcnow()).hour,
            pillar=pillar,
            content_type=content_type,
            topic=topic or f"{business.name} — {pillar.value}",
            platform=platform,
        )
        copy, review, visual = await self._compose(
            business,
            knowledge,
            slot,
            extra_instructions=extra_instructions,
            render_image=render_image,
        )
        item = self._build_item(
            business,
            plan,
            slot,
            copy,
            review,
            visual,
            start=utcnow().date(),
            scheduled_at=scheduled_at or utcnow(),
        )
        self.session.add(item)
        await self.session.flush()
        log.info("single_item_generated", business=str(business_id), item=str(item.id))
        return item

    # ------------------------------------------------------------------ #
    # Regeneration driven by owner feedback
    # ------------------------------------------------------------------ #
    async def regenerate(
        self,
        item: ContentItem,
        *,
        instruction: str = "",
        regenerate_image: bool = False,
    ) -> ContentItem:
        business = await self.businesses.get_full(item.business_id)
        if business is None:
            raise NotFoundError(f"Business {item.business_id} not found")
        knowledge = business.knowledge_base or await self.knowledge_repo.get_or_create(item.business_id)

        slot = PlanSlot(
            day_offset=0,
            hour=item.scheduled_at.hour,
            pillar=item.pillar,
            content_type=item.content_type,
            topic=item.topic or item.headline,
            platform=item.platform,
        )
        copy, review, visual = await self._compose(
            business,
            knowledge,
            slot,
            extra_instructions=instruction,
            previous_caption=item.caption_tg,
            render_image=regenerate_image,
        )

        item.headline = copy.headline[:300]
        item.hook = copy.hook[:300]
        item.cta = copy.cta[:300]
        item.caption_tg = copy.caption_tg
        item.caption_ig = copy.caption_ig
        item.hashtags = copy.hashtags
        item.options = copy.quiz or {}
        item.script = copy.script or {}
        item.quality_score = review.score
        item.editor_report = review.report.model_dump(mode="json")
        item.regeneration_count += 1
        item.status = ContentItemStatus.PENDING_REVIEW
        item.sent_for_review = False
        item.last_error = None
        if regenerate_image or not item.image_url or item.content_type == ContentType.CAROUSEL:
            self._apply_visual(item, visual, copy)

        await self.session.flush()
        log.info("item_regenerated", item=str(item.id), attempt=item.regeneration_count)
        return item
