"""Lead persistence — every phone number the bot captures lands here."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select

from app.models.lead import Lead
from app.repositories.base import BaseRepository


class LeadRepository(BaseRepository[Lead]):
    model = Lead

    async def add(
        self,
        *,
        business_id: uuid.UUID | None,
        telegram_user_id: int,
        full_name: str = "",
        username: str = "",
        phone: str = "",
        interest: str = "",
        source: str = "bot",
    ) -> Lead:
        lead = Lead(
            business_id=business_id,
            telegram_user_id=telegram_user_id,
            full_name=full_name[:160],
            username=username[:160],
            phone=phone[:64],
            interest=interest[:2000],
            source=source[:32],
        )
        self.session.add(lead)
        await self.session.flush()
        return lead

    async def counts_between(
        self, business_id: uuid.UUID, start: datetime, end: datetime
    ) -> dict[str, int]:
        """How many people wrote in during the period, by where they got to.

        `total` is what the owner paid for; the split between `new` and
        `contacted` is what their own team did with it, and putting both in
        one report keeps that distinction visible.
        """
        stmt = (
            select(Lead.status, func.count())
            .where(
                Lead.business_id == business_id,
                Lead.created_at >= start,
                Lead.created_at <= end,
            )
            .group_by(Lead.status)
        )
        rows = (await self.session.execute(stmt)).all()
        counts = {str(status): int(count) for status, count in rows}
        counts["total"] = sum(counts.values())
        return counts

    async def search(
        self,
        *,
        business_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[Lead], int]:
        stmt = select(Lead)
        if business_id is not None:
            stmt = stmt.where(Lead.business_id == business_id)
        if status:
            stmt = stmt.where(Lead.status == status)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            await self.session.execute(
                stmt.order_by(Lead.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()
        return rows, int(total)
