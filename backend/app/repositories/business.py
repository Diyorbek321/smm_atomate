"""Business, credentials, admin and knowledge-base data access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.business import Business, BusinessAdmin, BusinessCredentials
from app.models.enums import Plan
from app.models.knowledge_base import KnowledgeBase
from app.repositories.base import BaseRepository
from app.utils.text import slugify


class BusinessRepository(BaseRepository[Business]):
    model = Business

    async def get_full(self, business_id: uuid.UUID) -> Business | None:
        stmt = (
            select(Business)
            .where(Business.id == business_id)
            .options(
                selectinload(Business.credentials),
                selectinload(Business.knowledge_base),
                selectinload(Business.admins),
            )
        )
        return (await self.session.execute(stmt)).scalars().unique().one_or_none()

    async def get_full_or_404(self, business_id: uuid.UUID) -> Business:
        business = await self.get_full(business_id)
        if business is None:
            raise NotFoundError(f"Business {business_id} not found")
        return business

    async def by_slug(self, slug: str) -> Business | None:
        stmt = select(Business).where(Business.slug == slug)
        return (await self.session.execute(stmt)).scalars().one_or_none()

    async def list_active(self) -> Sequence[Business]:
        stmt = (
            select(Business)
            .where(Business.is_active.is_(True))
            .options(selectinload(Business.credentials), selectinload(Business.knowledge_base))
            .order_by(Business.created_at)
        )
        return (await self.session.execute(stmt)).scalars().unique().all()

    async def search(self, *, query: str | None = None, is_active: bool | None = None,
                     plan: Plan | None = None,
                     offset: int = 0, limit: int = 50) -> tuple[Sequence[Business], int]:
        stmt = select(Business)
        count_stmt = select(func.count()).select_from(Business)
        if query:
            pattern = f"%{query.lower()}%"
            stmt = stmt.where(func.lower(Business.name).like(pattern))
            count_stmt = count_stmt.where(func.lower(Business.name).like(pattern))
        if is_active is not None:
            stmt = stmt.where(Business.is_active.is_(is_active))
            count_stmt = count_stmt.where(Business.is_active.is_(is_active))
        if plan is not None:
            stmt = stmt.where(Business.plan == plan)
            count_stmt = count_stmt.where(Business.plan == plan)

        stmt = stmt.order_by(Business.created_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().unique().all()
        total = int((await self.session.execute(count_stmt)).scalar() or 0)
        return rows, total

    async def create_with_defaults(self, **values: Any) -> Business:
        """Create a business together with its empty KB + credentials rows."""
        slug = values.pop("slug", None) or slugify(str(values.get("name", "")))
        if await self.by_slug(slug):
            slug = f"{slug}-{uuid.uuid4().hex[:5]}"

        business = Business(slug=slug, **values)
        self.session.add(business)
        await self.session.flush()

        self.session.add(KnowledgeBase(business_id=business.id))
        self.session.add(BusinessCredentials(business_id=business.id))
        await self.session.flush()
        await self.session.refresh(business, ["knowledge_base", "credentials"])
        return business


class KnowledgeBaseRepository(BaseRepository[KnowledgeBase]):
    model = KnowledgeBase

    async def for_business(self, business_id: uuid.UUID) -> KnowledgeBase | None:
        stmt = select(KnowledgeBase).where(KnowledgeBase.business_id == business_id)
        return (await self.session.execute(stmt)).scalars().one_or_none()

    async def get_or_create(self, business_id: uuid.UUID) -> KnowledgeBase:
        knowledge = await self.for_business(business_id)
        if knowledge is None:
            knowledge = KnowledgeBase(business_id=business_id)
            self.session.add(knowledge)
            await self.session.flush()
        return knowledge


class CredentialsRepository(BaseRepository[BusinessCredentials]):
    model = BusinessCredentials

    async def for_business(self, business_id: uuid.UUID) -> BusinessCredentials | None:
        stmt = select(BusinessCredentials).where(BusinessCredentials.business_id == business_id)
        return (await self.session.execute(stmt)).scalars().one_or_none()

    async def get_or_create(self, business_id: uuid.UUID) -> BusinessCredentials:
        credentials = await self.for_business(business_id)
        if credentials is None:
            credentials = BusinessCredentials(business_id=business_id)
            self.session.add(credentials)
            await self.session.flush()
        return credentials


class AdminRepository(BaseRepository[BusinessAdmin]):
    model = BusinessAdmin

    async def for_business(self, business_id: uuid.UUID) -> Sequence[BusinessAdmin]:
        stmt = select(BusinessAdmin).where(BusinessAdmin.business_id == business_id)
        return (await self.session.execute(stmt)).scalars().all()

    async def by_telegram_user(self, telegram_user_id: int) -> Sequence[BusinessAdmin]:
        stmt = (
            select(BusinessAdmin)
            .where(BusinessAdmin.telegram_user_id == telegram_user_id)
            .options(selectinload(BusinessAdmin.business))
        )
        return (await self.session.execute(stmt)).scalars().unique().all()

    async def reviewers(self, business_id: uuid.UUID) -> Sequence[BusinessAdmin]:
        stmt = select(BusinessAdmin).where(
            BusinessAdmin.business_id == business_id,
            BusinessAdmin.receives_reviews.is_(True),
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def upsert(self, business_id: uuid.UUID, telegram_user_id: int, **values: Any) -> BusinessAdmin:
        stmt = select(BusinessAdmin).where(
            BusinessAdmin.business_id == business_id,
            BusinessAdmin.telegram_user_id == telegram_user_id,
        )
        admin = (await self.session.execute(stmt)).scalars().one_or_none()
        if admin is None:
            admin = BusinessAdmin(business_id=business_id, telegram_user_id=telegram_user_id, **values)
            self.session.add(admin)
        else:
            for key, value in values.items():
                if value is not None:
                    setattr(admin, key, value)
        await self.session.flush()
        return admin
