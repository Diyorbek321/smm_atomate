"""Generic async repository (see rules/common/patterns.md — Repository Pattern)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def get_or_404(self, entity_id: uuid.UUID) -> ModelT:
        entity = await self.get(entity_id)
        if entity is None:
            raise NotFoundError(f"{self.model.__name__} {entity_id} not found")
        return entity

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        order_by: Any = None,
        **filters: Any,
    ) -> Sequence[ModelT]:
        stmt = select(self.model)
        for field_name, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, field_name) == value)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.offset(offset).limit(limit)
        return (await self.session.execute(stmt)).scalars().all()

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        for field_name, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, field_name) == value)
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def create(self, **values: Any) -> ModelT:
        entity = self.model(**values)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ModelT, values: dict[str, Any]) -> ModelT:
        """Apply a partial update, ignoring `None` (PATCH semantics).

        The entity is refreshed after the flush so server-side values such as
        ``updated_at`` are loaded eagerly — serialising an expired attribute
        outside the greenlet context would otherwise raise ``MissingGreenlet``.
        """
        for key, value in values.items():
            if value is not None and hasattr(entity, key):
                setattr(entity, key, value)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()
