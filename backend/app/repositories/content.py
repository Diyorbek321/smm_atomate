"""Content plan / item / prompt data access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.models.content_item import SUPERSEDED_NOTE, ContentItem
from app.models.content_plan import ContentPlan
from app.models.enums import ContentItemStatus, ContentPlanStatus
from app.models.prompt_template import PromptTemplate
from app.models.publish_log import PublishLog
from app.repositories.base import BaseRepository
from app.utils.dates import iso_week, utcnow


class ContentPlanRepository(BaseRepository[ContentPlan]):
    model = ContentPlan

    async def get_with_items(self, plan_id: uuid.UUID) -> ContentPlan | None:
        stmt = (
            select(ContentPlan)
            .where(ContentPlan.id == plan_id)
            .options(selectinload(ContentPlan.items))
        )
        return (await self.session.execute(stmt)).scalars().unique().one_or_none()

    async def for_business(
        self, business_id: uuid.UUID, *, offset: int = 0, limit: int = 25
    ) -> tuple[Sequence[ContentPlan], int]:
        stmt = (
            select(ContentPlan)
            .where(ContentPlan.business_id == business_id)
            .order_by(ContentPlan.starts_on.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().unique().all()
        total = await self.count(business_id=business_id)
        return rows, total

    async def find_for_week(self, business_id: uuid.UUID, day: date) -> ContentPlan | None:
        year, week = iso_week(day)
        stmt = select(ContentPlan).where(
            ContentPlan.business_id == business_id,
            ContentPlan.year == year,
            ContentPlan.week_number == week,
        )
        return (await self.session.execute(stmt)).scalars().one_or_none()

    async def latest(self, business_id: uuid.UUID) -> ContentPlan | None:
        stmt = (
            select(ContentPlan)
            .where(ContentPlan.business_id == business_id)
            .order_by(ContentPlan.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def businesses_missing_plan(self, day: date) -> list[uuid.UUID]:
        """Business ids that have no plan for the ISO week containing `day`."""
        year, week = iso_week(day)
        stmt = select(ContentPlan.business_id).where(
            ContentPlan.year == year,
            ContentPlan.week_number == week,
            ContentPlan.status != ContentPlanStatus.ARCHIVED,
        )
        covered = set((await self.session.execute(stmt)).scalars().all())
        return list(covered)


class ContentItemRepository(BaseRepository[ContentItem]):
    model = ContentItem

    async def due_for_publishing(self, *, limit: int = 25, now: datetime | None = None) -> Sequence[ContentItem]:
        """Approved items whose scheduled time has arrived, oldest first."""
        stmt = (
            select(ContentItem)
            .where(
                ContentItem.status == ContentItemStatus.APPROVED,
                ContentItem.scheduled_at <= (now or utcnow()),
            )
            .order_by(ContentItem.scheduled_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def retryable_failures(self, *, max_retries: int, limit: int = 25) -> Sequence[ContentItem]:
        cutoff = utcnow() - timedelta(minutes=10)
        stmt = (
            select(ContentItem)
            .where(
                ContentItem.status == ContentItemStatus.FAILED,
                ContentItem.retry_count < max_retries,
                ContentItem.updated_at <= cutoff,
            )
            .order_by(ContentItem.updated_at)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def pending_review(self, *, business_id: uuid.UUID | None = None, limit: int = 50) -> Sequence[ContentItem]:
        stmt = select(ContentItem).where(ContentItem.status == ContentItemStatus.PENDING_REVIEW)
        if business_id:
            stmt = stmt.where(ContentItem.business_id == business_id)
        stmt = stmt.order_by(ContentItem.scheduled_at).limit(limit)
        return (await self.session.execute(stmt)).scalars().all()

    async def unsent_reviews(self, *, limit: int = 30) -> Sequence[ContentItem]:
        stmt = (
            select(ContentItem)
            .where(
                ContentItem.status == ContentItemStatus.PENDING_REVIEW,
                ContentItem.sent_for_review.is_(False),
            )
            .order_by(ContentItem.scheduled_at)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def search(
        self,
        *,
        business_id: uuid.UUID | None = None,
        content_plan_id: uuid.UUID | None = None,
        status: ContentItemStatus | None = None,
        content_type: Any = None,
        pillar: Any = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[ContentItem], int]:
        conditions = []
        if business_id:
            conditions.append(ContentItem.business_id == business_id)
        if content_plan_id:
            conditions.append(ContentItem.content_plan_id == content_plan_id)
        if status:
            conditions.append(ContentItem.status == status)
        if content_type:
            conditions.append(ContentItem.content_type == content_type)
        if pillar:
            conditions.append(ContentItem.pillar == pillar)
        if date_from:
            conditions.append(ContentItem.scheduled_at >= date_from)
        if date_to:
            conditions.append(ContentItem.scheduled_at <= date_to)

        where = and_(*conditions) if conditions else None
        stmt = select(ContentItem)
        count_stmt = select(func.count()).select_from(ContentItem)
        if where is not None:
            stmt = stmt.where(where)
            count_stmt = count_stmt.where(where)

        stmt = stmt.order_by(ContentItem.scheduled_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        total = int((await self.session.execute(count_stmt)).scalar() or 0)
        return rows, total

    async def recent_performance(
        self, business_id: uuid.UUID, *, days: int = 60, topics: int = 24
    ) -> dict[str, Any]:
        """What went out lately, how it landed, and what has already been said.

        Those are two different questions and they need two different windows.
        *How it landed* can only be asked of published posts — a draft nobody
        saw says nothing about what works. *What has already been covered* must
        include every draft, because a topic the planner wrote last Tuesday is
        used up whether or not the owner approved it.

        Reading only published rows conflated the two, and on an account that
        reviews before publishing it left the planner with almost no memory: it
        proposed the same handful of topics every run, the owner rejected them,
        the rejections were invisible, and the next run proposed them again.
        """
        since = utcnow() - timedelta(days=days)
        stmt = (
            select(ContentItem)
            .where(
                ContentItem.business_id == business_id,
                ContentItem.status == ContentItemStatus.PUBLISHED,
                ContentItem.published_at.is_not(None),
                ContentItem.published_at >= since,
            )
            .order_by(ContentItem.published_at.desc())
        )
        items = list((await self.session.execute(stmt)).scalars().all())

        by_pillar: dict[str, dict[str, float]] = {}
        for item in items:
            bucket = by_pillar.setdefault(
                item.pillar.value,
                {"posts": 0, "reactions": 0, "measured": 0, "views": 0, "viewed": 0},
            )
            bucket["posts"] += 1
            metrics = item.metrics or {}
            reactions = metrics.get("reactions")
            if isinstance(reactions, int):
                bucket["reactions"] += reactions
                bucket["measured"] += 1
            # Reach, collected off the public channel page — see
            # `app.tasks.metrics`. Counted separately from reactions because
            # the two cover different posts: every post gets views, only a
            # pressed one gets reactions.
            views = metrics.get("views")
            if isinstance(views, int) and views > 0:
                bucket["views"] += views
                bucket["viewed"] += 1
        for bucket in by_pillar.values():
            measured = bucket["measured"]
            bucket["avg_reactions"] = round(bucket["reactions"] / measured, 1) if measured else None
            viewed = bucket["viewed"]
            bucket["avg_views"] = round(bucket["views"] / viewed) if viewed else None

        covered, rejected = await self._covered_topics(business_id, since=since, limit=topics)
        return {
            "published": len(items),
            "by_pillar": by_pillar,
            #: Everything the pipeline has already written about, whatever
            #: became of it — not just what reached a follower.
            "recent_topics": covered,
            #: The subset the owner personally turned down. The strongest
            #: "do not write this again" signal the system ever receives, and
            #: until now the only one it threw away.
            "rejected_topics": rejected,
        }

    async def _covered_topics(
        self, business_id: uuid.UUID, *, since: datetime, limit: int
    ) -> tuple[list[str], list[str]]:
        """(everything already covered, what the owner rejected), newest first.

        A plan regeneration retires the previous drafts by rejecting them, so
        `REJECTED` on its own does not mean the owner disliked anything — see
        `SUPERSEDED_NOTE`. Those rows still count as covered ground; they just
        do not count as feedback.
        """
        stmt = (
            select(ContentItem.topic, ContentItem.status, ContentItem.review_notes)
            .where(
                ContentItem.business_id == business_id,
                ContentItem.created_at >= since,
                ContentItem.status.in_(
                    [
                        ContentItemStatus.PUBLISHED,
                        ContentItemStatus.APPROVED,
                        ContentItemStatus.PENDING_REVIEW,
                        ContentItemStatus.REJECTED,
                    ]
                ),
            )
            .order_by(ContentItem.created_at.desc())
            .limit(limit * 4)
        )
        covered: list[str] = []
        rejected: list[str] = []
        seen: set[str] = set()
        for topic, status, notes in (await self.session.execute(stmt)).all():
            topic = (topic or "").strip()
            key = topic.lower()
            if not topic or key in seen:
                continue
            seen.add(key)
            covered.append(topic)
            if status == ContentItemStatus.REJECTED and (notes or "").strip() != SUPERSEDED_NOTE:
                rejected.append(topic)
        return covered[:limit], rejected[:limit]

    async def produced_between(
        self, business_id: uuid.UUID, *, days: int = 30, limit: int = 400
    ) -> Sequence[ContentItem]:
        """Everything the pipeline *made* in the window, whatever became of it.

        `recent_performance` only looks at what was published, because that is
        the question a planner asks. The analyst asks the other one: how the
        machine behaved — what got rejected, rewritten, or failed to publish.
        Those rows are invisible to any published-only query.
        """
        since = utcnow() - timedelta(days=days)
        stmt = (
            select(ContentItem)
            .where(
                ContentItem.business_id == business_id,
                ContentItem.created_at >= since,
            )
            .order_by(ContentItem.created_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def published_between(
        self, business_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[ContentItem]:
        """Everything that actually reached a follower in the period."""
        stmt = (
            select(ContentItem)
            .where(
                ContentItem.business_id == business_id,
                ContentItem.status == ContentItemStatus.PUBLISHED,
                ContentItem.published_at.is_not(None),
                ContentItem.published_at >= start,
                ContentItem.published_at <= end,
            )
            .order_by(ContentItem.published_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def recent_subjects(
        self, business_id: uuid.UUID, *, days: int = 30, limit: int = 60
    ) -> list[tuple[str, str]]:
        """`(headline, topic)` for everything written lately, newest first.

        Rejected drafts are included on purpose: the owner turning a post down
        is the strongest possible signal not to write it again next week.

        The two fields are kept apart rather than joined into one string. They
        are compared against a candidate's own headline and topic, and an
        overlap measure divides by the shorter of the two token sets — so
        gluing a long headline to a short topic changes the answer in both
        directions. A repeated topic hides inside the padding, and a short
        headline scores as "contained in" any long line that happens to use
        its words.
        """
        since = utcnow() - timedelta(days=days)
        stmt = (
            select(ContentItem.headline, ContentItem.topic)
            .where(
                ContentItem.business_id == business_id,
                ContentItem.created_at >= since,
                ContentItem.status.in_(
                    [
                        ContentItemStatus.PUBLISHED,
                        ContentItemStatus.APPROVED,
                        ContentItemStatus.PENDING_REVIEW,
                        ContentItemStatus.REJECTED,
                    ]
                ),
            )
            .order_by(ContentItem.created_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        subjects = [((headline or "").strip(), (topic or "").strip()) for headline, topic in rows]
        return [pair for pair in subjects if any(pair)]

    async def by_telegram_message(
        self, message_id: str, *, business_id: uuid.UUID | None = None
    ) -> ContentItem | None:
        """The item a channel message came from, by its Telegram message id.

        A message id is unique **within a channel**, never across them: two
        clients both have a message 9, and they are different posts. Pass
        `business_id` wherever the caller knows it — without it this returns
        whichever row happens to come first, which is how one client's numbers
        end up on another client's post.
        """
        stmt = select(ContentItem).where(ContentItem.tg_message_id == str(message_id))
        if business_id is not None:
            stmt = stmt.where(ContentItem.business_id == business_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def by_telegram_messages(
        self, business_id: uuid.UUID, message_ids: list[str]
    ) -> Sequence[ContentItem]:
        """The same lookup for a whole page of messages, in one query."""
        if not message_ids:
            return []
        stmt = select(ContentItem).where(
            ContentItem.business_id == business_id,
            ContentItem.tg_message_id.in_([str(m) for m in message_ids]),
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def by_ids(self, item_ids: list[uuid.UUID]) -> Sequence[ContentItem]:
        if not item_ids:
            return []
        stmt = select(ContentItem).where(ContentItem.id.in_(item_ids))
        return (await self.session.execute(stmt)).scalars().all()

    async def status_counts(self, business_id: uuid.UUID | None = None) -> dict[str, int]:
        stmt = select(ContentItem.status, func.count()).group_by(ContentItem.status)
        if business_id:
            stmt = stmt.where(ContentItem.business_id == business_id)
        rows = (await self.session.execute(stmt)).all()
        return {str(status): int(count) for status, count in rows}

    async def pillar_counts(self, business_id: uuid.UUID | None = None) -> dict[str, int]:
        stmt = select(ContentItem.pillar, func.count()).group_by(ContentItem.pillar)
        if business_id:
            stmt = stmt.where(ContentItem.business_id == business_id)
        rows = (await self.session.execute(stmt)).all()
        return {str(pillar): int(count) for pillar, count in rows}

    async def type_counts(self, business_id: uuid.UUID | None = None) -> dict[str, int]:
        stmt = select(ContentItem.content_type, func.count()).group_by(ContentItem.content_type)
        if business_id:
            stmt = stmt.where(ContentItem.business_id == business_id)
        rows = (await self.session.execute(stmt)).all()
        return {str(kind): int(count) for kind, count in rows}

    async def count_between(
        self,
        start: datetime,
        end: datetime,
        *,
        statuses: list[ContentItemStatus] | None = None,
        business_id: uuid.UUID | None = None,
        field: str = "scheduled_at",
    ) -> int:
        column = getattr(ContentItem, field)
        stmt = select(func.count()).select_from(ContentItem).where(column >= start, column <= end)
        if statuses:
            stmt = stmt.where(ContentItem.status.in_(statuses))
        if business_id:
            stmt = stmt.where(ContentItem.business_id == business_id)
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def upcoming(self, *, limit: int = 10, business_id: uuid.UUID | None = None) -> Sequence[ContentItem]:
        stmt = (
            select(ContentItem)
            .where(
                ContentItem.scheduled_at >= utcnow(),
                ContentItem.status.in_([ContentItemStatus.APPROVED, ContentItemStatus.PENDING_REVIEW]),
            )
            .order_by(ContentItem.scheduled_at)
            .limit(limit)
        )
        if business_id:
            stmt = stmt.where(ContentItem.business_id == business_id)
        return (await self.session.execute(stmt)).scalars().all()

    async def average_quality(self, business_id: uuid.UUID | None = None) -> float:
        stmt = select(func.avg(ContentItem.quality_score)).where(ContentItem.quality_score > 0)
        if business_id:
            stmt = stmt.where(ContentItem.business_id == business_id)
        return round(float((await self.session.execute(stmt)).scalar() or 0.0), 2)

    async def last_published_at(self, business_id: uuid.UUID) -> datetime | None:
        stmt = select(func.max(ContentItem.published_at)).where(ContentItem.business_id == business_id)
        return (await self.session.execute(stmt)).scalar()

    async def find_by_review_message(self, chat_id: int, message_id: int) -> ContentItem | None:
        stmt = select(ContentItem).where(
            ContentItem.review_chat_id == chat_id,
            ContentItem.review_message_id == message_id,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def stale_generating(self, older_than_minutes: int = 30) -> Sequence[ContentItem]:
        cutoff = utcnow() - timedelta(minutes=older_than_minutes)
        stmt = select(ContentItem).where(
            or_(
                and_(ContentItem.status == ContentItemStatus.GENERATING, ContentItem.updated_at < cutoff),
                and_(ContentItem.status == ContentItemStatus.PUBLISHING, ContentItem.updated_at < cutoff),
            )
        )
        return (await self.session.execute(stmt)).scalars().all()


class PromptRepository(BaseRepository[PromptTemplate]):
    model = PromptTemplate

    async def search(
        self, *, business_id: uuid.UUID | None = None, agent: str | None = None,
        offset: int = 0, limit: int = 50
    ) -> tuple[Sequence[PromptTemplate], int]:
        stmt = select(PromptTemplate)
        count_stmt = select(func.count()).select_from(PromptTemplate)
        if business_id:
            stmt = stmt.where(PromptTemplate.business_id == business_id)
            count_stmt = count_stmt.where(PromptTemplate.business_id == business_id)
        if agent:
            stmt = stmt.where(PromptTemplate.agent == agent)
            count_stmt = count_stmt.where(PromptTemplate.agent == agent)
        stmt = stmt.order_by(PromptTemplate.updated_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        total = int((await self.session.execute(count_stmt)).scalar() or 0)
        return rows, total


class PublishLogRepository(BaseRepository[PublishLog]):
    model = PublishLog

    async def for_item(self, item_id: uuid.UUID, limit: int = 20) -> Sequence[PublishLog]:
        stmt = (
            select(PublishLog)
            .where(PublishLog.content_item_id == item_id)
            .order_by(PublishLog.created_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def recent_failures(self, hours: int = 24, limit: int = 50) -> Sequence[PublishLog]:
        cutoff = utcnow() - timedelta(hours=hours)
        stmt = (
            select(PublishLog)
            .where(PublishLog.created_at >= cutoff, PublishLog.state == "failed")
            .order_by(PublishLog.created_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()
