"""Reading and writing the video path's structural memory."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.clip_shape import ClipShape
from app.repositories.base import BaseRepository
from app.services.promo_variety import HISTORY, Shape


class ClipShapeRepository(BaseRepository[ClipShape]):
    model = ClipShape

    async def record(
        self,
        *,
        business_id: uuid.UUID,
        topic: str,
        shape: Shape,
        seconds: int = 0,
    ) -> ClipShape:
        row = ClipShape(
            business_id=business_id,
            topic=topic[:300],
            skeleton=shape.skeleton[:32],
            opening=shape.opening[:48],
            archetypes=list(shape.archetypes),
            scenes=shape.scenes,
            mood=shape.mood[:24],
            backdrop=shape.backdrop[:160],
            seconds=int(seconds),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent(
        self, business_id: uuid.UUID, *, limit: int = HISTORY
    ) -> list[Shape]:
        """The last clips' shapes, newest first.

        No date window, unlike :meth:`ContentItemRepository.recent_subjects`.
        A topic goes stale — last September's intake is not this September's —
        but a skeleton does not: opening six clips in a row the same way reads
        as repetition whether they were made this week or last quarter, and a
        business that ships one clip a month would otherwise always see an
        empty history and always get the same shape.
        """
        stmt = (
            select(ClipShape)
            .where(ClipShape.business_id == business_id)
            .order_by(ClipShape.created_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [Shape.from_row(row) for row in rows]
