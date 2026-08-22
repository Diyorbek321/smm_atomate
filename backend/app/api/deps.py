"""FastAPI dependencies: auth, pagination, common repositories."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import verify_api_key
from app.db.session import get_session
from app.models.business import Business
from app.repositories.business import BusinessRepository
from app.schemas.common import PaginationParams

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def require_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> str:
    """Static API-key guard for the admin dashboard.

    Disabled in development when no key is configured, so the dashboard can be
    wired up before secrets exist.
    """
    placeholder = not settings.api_key or settings.api_key == "change-me-super-secret-api-key"
    if placeholder and not settings.is_production:
        return "dev"
    if not verify_api_key(x_api_key):
        raise UnauthorizedError("Invalid or missing X-API-Key header")
    return x_api_key or ""


AuthDep = Annotated[str, Depends(require_api_key)]


async def pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> PaginationParams:
    return PaginationParams(page=page, limit=limit)


PaginationDep = Annotated[PaginationParams, Depends(pagination)]


async def get_business(
    business_id: Annotated[uuid.UUID, Path()],
    session: SessionDep,
) -> Business:
    """Load a business with credentials + knowledge base or raise 404."""
    return await BusinessRepository(session).get_full_or_404(business_id)


BusinessDep = Annotated[Business, Depends(get_business)]
