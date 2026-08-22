"""Dashboard analytics endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import AuthDep, SessionDep
from app.repositories.content import PublishLogRepository
from app.schemas.common import APIResponse
from app.schemas.generation import AnalyticsSummary, BusinessAnalytics
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=APIResponse[AnalyticsSummary])
async def summary(session: SessionDep, _: AuthDep) -> APIResponse[AnalyticsSummary]:
    return APIResponse.ok(await AnalyticsService(session).summary())


@router.get("/business/{business_id}", response_model=APIResponse[BusinessAnalytics])
async def business_analytics(
    business_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[BusinessAnalytics]:
    return APIResponse.ok(await AnalyticsService(session).for_business(business_id))


@router.get("/failures", response_model=APIResponse[list[dict]])
async def recent_failures(session: SessionDep, _: AuthDep, hours: int = 24) -> APIResponse[list[dict]]:
    logs = await PublishLogRepository(session).recent_failures(hours=hours)
    return APIResponse.ok(
        [
            {
                "item_id": str(entry.content_item_id),
                "business_id": str(entry.business_id),
                "platform": str(entry.platform),
                "attempt": entry.attempt,
                "message": entry.message,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in logs
        ]
    )
