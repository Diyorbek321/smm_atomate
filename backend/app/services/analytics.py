"""Dashboard analytics aggregation."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business import Business
from app.models.enums import ContentItemStatus
from app.models.knowledge_base import KnowledgeBase
from app.repositories.content import ContentItemRepository
from app.schemas.generation import AnalyticsSummary, BusinessAnalytics
from app.utils.dates import to_local, utcnow

#: Rough blended cost of one generated item (Gemini + Flux), USD.
EST_COST_PER_ITEM = 0.012


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.items = ContentItemRepository(session)

    async def summary(self) -> AnalyticsSummary:
        now = utcnow()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        last_24h = now - timedelta(hours=24)

        total_businesses = int(
            (await self.session.execute(select(func.count()).select_from(Business))).scalar() or 0
        )
        active_businesses = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(Business).where(Business.is_active.is_(True))
                )
            ).scalar()
            or 0
        )

        status_counts = await self.items.status_counts()
        published_total = status_counts.get(ContentItemStatus.PUBLISHED.value, 0)
        pending_review = status_counts.get(ContentItemStatus.PENDING_REVIEW.value, 0)

        scheduled_today = await self.items.count_between(
            day_start, day_end, statuses=[ContentItemStatus.APPROVED, ContentItemStatus.PENDING_REVIEW]
        )
        published_24h = await self.items.count_between(
            last_24h, now, statuses=[ContentItemStatus.PUBLISHED], field="published_at"
        )
        failed_24h = await self.items.count_between(
            last_24h, now, statuses=[ContentItemStatus.FAILED], field="updated_at"
        )

        reviewed = published_total + status_counts.get(ContentItemStatus.REJECTED.value, 0)
        approval_rate = round(published_total / reviewed, 3) if reviewed else 0.0

        total_items = sum(status_counts.values())
        upcoming = await self.items.upcoming(limit=8)

        return AnalyticsSummary(
            active_businesses=active_businesses,
            total_businesses=total_businesses,
            scheduled_today=scheduled_today,
            pending_review=pending_review,
            published_24h=published_24h,
            failed_24h=failed_24h,
            published_total=published_total,
            approval_rate=approval_rate,
            avg_quality_score=await self.items.average_quality(),
            pillar_distribution=await self.items.pillar_counts(),
            content_type_distribution=await self.items.type_counts(),
            upcoming=[
                {
                    "id": str(item.id),
                    "business_id": str(item.business_id),
                    "title": item.short_title(),
                    "content_type": str(item.content_type),
                    "status": str(item.status),
                    "scheduled_at": to_local(item.scheduled_at).isoformat(),
                }
                for item in upcoming
            ],
            est_api_cost_usd=round(total_items * EST_COST_PER_ITEM, 2),
        )

    async def for_business(self, business_id: uuid.UUID) -> BusinessAnalytics:
        business = await self.session.get(Business, business_id)
        name = business.name if business else str(business_id)

        status_counts = await self.items.status_counts(business_id)
        published = status_counts.get(ContentItemStatus.PUBLISHED.value, 0)
        rejected = status_counts.get(ContentItemStatus.REJECTED.value, 0)
        reviewed = published + rejected

        knowledge = (
            await self.session.execute(select(KnowledgeBase).where(KnowledgeBase.business_id == business_id))
        ).scalars().one_or_none()

        return BusinessAnalytics(
            business_id=business_id,
            business_name=name,
            items_total=sum(status_counts.values()),
            published=published,
            pending_review=status_counts.get(ContentItemStatus.PENDING_REVIEW.value, 0),
            failed=status_counts.get(ContentItemStatus.FAILED.value, 0),
            approval_rate=round(published / reviewed, 3) if reviewed else 0.0,
            avg_quality_score=await self.items.average_quality(business_id),
            knowledge_completeness=knowledge.completeness_score if knowledge else 0.0,
            by_pillar=await self.items.pillar_counts(business_id),
            last_published_at=await self.items.last_published_at(business_id),
        )

    async def item_counts_by_status(self, business_id: uuid.UUID | None = None) -> dict[str, int]:
        return await self.items.status_counts(business_id)


async def business_content_health(session: AsyncSession, business_id: uuid.UUID) -> dict[str, object]:
    """Quick health probe surfaced in the bot's /status command."""
    repo = ContentItemRepository(session)
    now = utcnow()
    upcoming = await repo.count_between(now, now + timedelta(days=7), statuses=[ContentItemStatus.APPROVED],
                                        business_id=business_id)
    pending = len(await repo.pending_review(business_id=business_id, limit=200))
    return {
        "approved_next_7d": upcoming,
        "pending_review": pending,
        "avg_quality": await repo.average_quality(business_id),
    }
