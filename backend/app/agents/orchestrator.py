"""ContentPipeline — wires Strategist → Copywriter → Visual → Editor together."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentUsage
from app.agents.copywriter import CopyRequest, CopywriterAgent
from app.agents.editor import EditorAgent, EditorRequest, EditorResult
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

        strategy = await self._strategy(business, knowledge, start, horizon_days, total, extra_instructions)
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

    async def _strategy(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        start: date,
        horizon_days: int,
        total: int,
        extra_instructions: str,
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

        review = await editor.run(
            EditorRequest(
                business=business,
                knowledge=knowledge,
                copy=copy,
                content_type=slot.content_type,
                topic=slot.topic,
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
                )
            )

        copy = review.copy
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
            )
        )
        return copy, review, visual

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
