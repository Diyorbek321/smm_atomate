"""Leads captured by the bot — list them and mark them contacted."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from app.api.deps import AuthDep, PaginationDep, SessionDep
from app.core.exceptions import ValidationError
from app.repositories.lead import LeadRepository
from app.schemas.common import APIResponse, PageMeta

router = APIRouter(prefix="/leads", tags=["leads"])

LEAD_STATUSES = {"new", "contacted"}


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID | None
    telegram_user_id: int
    full_name: str
    username: str
    phone: str
    interest: str
    source: str
    status: str
    created_at: datetime


class LeadStatusUpdate(BaseModel):
    status: str


@router.get("", response_model=APIResponse[list[LeadRead]])
async def list_leads(
    session: SessionDep,
    _: AuthDep,
    page: PaginationDep,
    business_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> APIResponse[list[LeadRead]]:
    rows, total = await LeadRepository(session).search(
        business_id=business_id, status=status, offset=page.offset, limit=page.limit
    )
    return APIResponse.ok(
        [LeadRead.model_validate(row) for row in rows],
        meta=PageMeta(total=total, page=page.page, limit=page.limit),
    )


@router.patch("/{lead_id}", response_model=APIResponse[LeadRead])
async def update_lead_status(
    lead_id: uuid.UUID, payload: LeadStatusUpdate, session: SessionDep, _: AuthDep
) -> APIResponse[LeadRead]:
    if payload.status not in LEAD_STATUSES:
        raise ValidationError(f"status must be one of {sorted(LEAD_STATUSES)}")
    repo = LeadRepository(session)
    lead = await repo.get_or_404(lead_id)
    lead.status = payload.status
    await session.flush()
    return APIResponse.ok(LeadRead.model_validate(lead))
