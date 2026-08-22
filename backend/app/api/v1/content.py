"""Content plans and the content queue."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AuthDep, PaginationDep, SessionDep
from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import (
    TERMINAL_ITEM_STATUSES,
    ContentItemStatus,
    ContentPillar,
    ContentPlanStatus,
    ContentType,
)
from app.repositories.business import BusinessRepository
from app.repositories.content import ContentItemRepository, ContentPlanRepository, PublishLogRepository
from app.schemas.common import APIResponse, MessageResponse, PageMeta
from app.schemas.content import (
    BulkStatusUpdate,
    ContentItemCreate,
    ContentItemRead,
    ContentItemUpdate,
    ContentPlanDetail,
    ContentPlanRead,
    ContentPlanUpdate,
)
from app.utils.dates import utcnow

router = APIRouter(tags=["content"])


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #
@router.get("/plans", response_model=APIResponse[list[ContentPlanRead]])
async def list_plans(
    session: SessionDep,
    _: AuthDep,
    page: PaginationDep,
    business_id: Annotated[uuid.UUID | None, Query()] = None,
) -> APIResponse[list[ContentPlanRead]]:
    repo = ContentPlanRepository(session)
    if business_id:
        rows, total = await repo.for_business(business_id, offset=page.offset, limit=page.limit)
    else:
        rows = await repo.list(offset=page.offset, limit=page.limit)
        total = await repo.count()
    return APIResponse.ok(
        [ContentPlanRead.model_validate(row) for row in rows],
        meta=PageMeta(total=total, page=page.page, limit=page.limit),
    )


@router.get("/plans/{plan_id}", response_model=APIResponse[ContentPlanDetail])
async def get_plan(plan_id: uuid.UUID, session: SessionDep, _: AuthDep) -> APIResponse[ContentPlanDetail]:
    plan = await ContentPlanRepository(session).get_with_items(plan_id)
    if plan is None:
        raise NotFoundError(f"Content plan {plan_id} not found")
    detail = ContentPlanDetail.model_validate(plan)
    detail.items = [ContentItemRead.model_validate(item) for item in plan.items]
    detail.pillar_counts = plan.pillar_counts
    return APIResponse.ok(detail)


@router.patch("/plans/{plan_id}", response_model=APIResponse[ContentPlanRead])
async def update_plan(
    plan_id: uuid.UUID, payload: ContentPlanUpdate, session: SessionDep, _: AuthDep
) -> APIResponse[ContentPlanRead]:
    repo = ContentPlanRepository(session)
    plan = await repo.get_or_404(plan_id)
    await repo.update(plan, payload.model_dump(exclude_unset=True))
    return APIResponse.ok(ContentPlanRead.model_validate(plan))


@router.post("/plans/{plan_id}/approve", response_model=APIResponse[dict])
async def approve_plan(plan_id: uuid.UUID, session: SessionDep, _: AuthDep) -> APIResponse[dict]:
    """One-click approval of every pending item in the plan."""
    plan = await ContentPlanRepository(session).get_with_items(plan_id)
    if plan is None:
        raise NotFoundError(f"Content plan {plan_id} not found")

    approved = 0
    for item in plan.items:
        if item.status in (ContentItemStatus.PENDING_REVIEW, ContentItemStatus.DRAFT):
            item.status = ContentItemStatus.APPROVED
            item.reviewed_at = utcnow()
            approved += 1
    plan.status = ContentPlanStatus.APPROVED
    await session.flush()
    return APIResponse.ok({"plan_id": str(plan_id), "approved": approved})


@router.delete("/plans/{plan_id}", response_model=APIResponse[MessageResponse])
async def delete_plan(plan_id: uuid.UUID, session: SessionDep, _: AuthDep) -> APIResponse[MessageResponse]:
    repo = ContentPlanRepository(session)
    await repo.delete(await repo.get_or_404(plan_id))
    return APIResponse.ok(MessageResponse(message="Plan deleted"))


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #
@router.get("/items", response_model=APIResponse[list[ContentItemRead]])
async def list_items(
    session: SessionDep,
    _: AuthDep,
    page: PaginationDep,
    business_id: Annotated[uuid.UUID | None, Query()] = None,
    content_plan_id: Annotated[uuid.UUID | None, Query()] = None,
    item_status: Annotated[ContentItemStatus | None, Query(alias="status")] = None,
    content_type: Annotated[ContentType | None, Query()] = None,
    pillar: Annotated[ContentPillar | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> APIResponse[list[ContentItemRead]]:
    rows, total = await ContentItemRepository(session).search(
        business_id=business_id,
        content_plan_id=content_plan_id,
        status=item_status,
        content_type=content_type,
        pillar=pillar,
        date_from=date_from,
        date_to=date_to,
        offset=page.offset,
        limit=page.limit,
    )
    return APIResponse.ok(
        [ContentItemRead.model_validate(row) for row in rows],
        meta=PageMeta(total=total, page=page.page, limit=page.limit),
    )


@router.post("/items", response_model=APIResponse[ContentItemRead], status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: ContentItemCreate, session: SessionDep, _: AuthDep
) -> APIResponse[ContentItemRead]:
    await BusinessRepository(session).get_or_404(payload.business_id)
    item = await ContentItemRepository(session).create(**payload.model_dump())
    return APIResponse.ok(ContentItemRead.model_validate(item))


@router.get("/items/{item_id}", response_model=APIResponse[ContentItemRead])
async def get_item(item_id: uuid.UUID, session: SessionDep, _: AuthDep) -> APIResponse[ContentItemRead]:
    item = await ContentItemRepository(session).get_or_404(item_id)
    return APIResponse.ok(ContentItemRead.model_validate(item))


@router.patch("/items/{item_id}", response_model=APIResponse[ContentItemRead])
async def update_item(
    item_id: uuid.UUID, payload: ContentItemUpdate, session: SessionDep, _: AuthDep
) -> APIResponse[ContentItemRead]:
    repo = ContentItemRepository(session)
    item = await repo.get_or_404(item_id)
    if item.status == ContentItemStatus.PUBLISHED:
        raise ConflictError("Published items cannot be edited")
    await repo.update(item, payload.model_dump(exclude_unset=True))
    return APIResponse.ok(ContentItemRead.model_validate(item))


@router.post("/items/{item_id}/approve", response_model=APIResponse[ContentItemRead])
async def approve_item(item_id: uuid.UUID, session: SessionDep, _: AuthDep) -> APIResponse[ContentItemRead]:
    repo = ContentItemRepository(session)
    item = await repo.get_or_404(item_id)
    if item.status in TERMINAL_ITEM_STATUSES:
        raise ConflictError(f"Item is already {item.status}")
    item.status = ContentItemStatus.APPROVED
    item.reviewed_at = utcnow()
    await session.flush()
    return APIResponse.ok(ContentItemRead.model_validate(item))


@router.post("/items/{item_id}/reject", response_model=APIResponse[ContentItemRead])
async def reject_item(item_id: uuid.UUID, session: SessionDep, _: AuthDep) -> APIResponse[ContentItemRead]:
    repo = ContentItemRepository(session)
    item = await repo.get_or_404(item_id)
    item.status = ContentItemStatus.REJECTED
    item.reviewed_at = utcnow()
    await session.flush()
    return APIResponse.ok(ContentItemRead.model_validate(item))


@router.post("/items/bulk-status", response_model=APIResponse[dict])
async def bulk_status(payload: BulkStatusUpdate, session: SessionDep, _: AuthDep) -> APIResponse[dict]:
    repo = ContentItemRepository(session)
    items = await repo.by_ids(payload.item_ids)
    changed = 0
    for item in items:
        if item.status == ContentItemStatus.PUBLISHED:
            continue
        item.status = payload.status
        item.reviewed_at = utcnow()
        changed += 1
    await session.flush()
    return APIResponse.ok({"requested": len(payload.item_ids), "updated": changed})


@router.delete("/items/{item_id}", response_model=APIResponse[MessageResponse])
async def delete_item(item_id: uuid.UUID, session: SessionDep, _: AuthDep) -> APIResponse[MessageResponse]:
    repo = ContentItemRepository(session)
    await repo.delete(await repo.get_or_404(item_id))
    return APIResponse.ok(MessageResponse(message="Item deleted"))


@router.get("/items/{item_id}/logs", response_model=APIResponse[list[dict]])
async def item_logs(item_id: uuid.UUID, session: SessionDep, _: AuthDep) -> APIResponse[list[dict]]:
    logs = await PublishLogRepository(session).for_item(item_id)
    return APIResponse.ok(
        [
            {
                "platform": str(entry.platform),
                "state": str(entry.state),
                "attempt": entry.attempt,
                "external_id": entry.external_id,
                "message": entry.message,
                "duration_ms": entry.duration_ms,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in logs
        ]
    )
