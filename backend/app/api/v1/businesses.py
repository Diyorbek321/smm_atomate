"""CRUD for businesses, credentials, knowledge base and admins."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status

from app.api.deps import AuthDep, BusinessDep, PaginationDep, SessionDep
from app.core.exceptions import ConfigurationError, NotFoundError, ValidationError
from app.models.enums import Plan
from app.repositories.business import (
    AdminRepository,
    BusinessRepository,
    CredentialsRepository,
    KnowledgeBaseRepository,
)
from app.schemas.business import (
    AdminCreate,
    AdminRead,
    BusinessCreate,
    BusinessRead,
    BusinessUpdate,
    CredentialsRead,
    CredentialsUpdate,
)
from app.schemas.common import APIResponse, MessageResponse, PageMeta
from app.schemas.knowledge_base import KnowledgeBaseRead, KnowledgeBaseUpdate

router = APIRouter(prefix="/businesses", tags=["businesses"])


@router.get("", response_model=APIResponse[list[BusinessRead]])
async def list_businesses(
    session: SessionDep,
    _: AuthDep,
    page: PaginationDep,
    q: Annotated[str | None, Query(description="Search by name")] = None,
    is_active: Annotated[bool | None, Query()] = None,
    plan: Annotated[Plan | None, Query(description="Filter by service tier")] = None,
) -> APIResponse[list[BusinessRead]]:
    rows, total = await BusinessRepository(session).search(
        query=q, is_active=is_active, plan=plan, offset=page.offset, limit=page.limit
    )
    return APIResponse.ok(
        [BusinessRead.model_validate(row) for row in rows],
        meta=PageMeta(total=total, page=page.page, limit=page.limit),
    )


@router.post("", response_model=APIResponse[BusinessRead], status_code=status.HTTP_201_CREATED)
async def create_business(
    payload: BusinessCreate, session: SessionDep, _: AuthDep
) -> APIResponse[BusinessRead]:
    business = await BusinessRepository(session).create_with_defaults(**payload.model_dump())
    return APIResponse.ok(BusinessRead.model_validate(business))


@router.get("/{business_id}", response_model=APIResponse[BusinessRead])
async def get_business_detail(business: BusinessDep, _: AuthDep) -> APIResponse[BusinessRead]:
    return APIResponse.ok(BusinessRead.model_validate(business))


@router.patch("/{business_id}", response_model=APIResponse[BusinessRead])
async def update_business(
    business: BusinessDep, payload: BusinessUpdate, session: SessionDep, _: AuthDep
) -> APIResponse[BusinessRead]:
    updated = await BusinessRepository(session).update(business, payload.model_dump(exclude_unset=True))
    return APIResponse.ok(BusinessRead.model_validate(updated))


@router.delete("/{business_id}", response_model=APIResponse[MessageResponse])
async def delete_business(
    business: BusinessDep, session: SessionDep, _: AuthDep
) -> APIResponse[MessageResponse]:
    await BusinessRepository(session).delete(business)
    return APIResponse.ok(MessageResponse(message="Business deleted"))


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
@router.get("/{business_id}/credentials", response_model=APIResponse[CredentialsRead])
async def get_credentials(
    business_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[CredentialsRead]:
    credentials = await CredentialsRepository(session).get_or_create(business_id)
    data = CredentialsRead.model_validate(credentials)
    data.telegram_ready = credentials.telegram_ready
    data.instagram_ready = credentials.instagram_ready
    return APIResponse.ok(data)


@router.put("/{business_id}/credentials", response_model=APIResponse[CredentialsRead])
async def update_credentials(
    business_id: uuid.UUID, payload: CredentialsUpdate, session: SessionDep, _: AuthDep
) -> APIResponse[CredentialsRead]:
    repo = CredentialsRepository(session)
    credentials = await repo.get_or_create(business_id)
    await repo.update(credentials, payload.model_dump(exclude_unset=True))
    data = CredentialsRead.model_validate(credentials)
    data.telegram_ready = credentials.telegram_ready
    data.instagram_ready = credentials.instagram_ready
    return APIResponse.ok(data)


@router.post("/{business_id}/credentials/verify", response_model=APIResponse[dict])
async def verify_credentials(
    business_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[dict]:
    """Live check that the stored tokens actually work."""
    from app.services.instagram_publisher import InstagramPublisher
    from app.services.telegram_publisher import TelegramPublisher

    credentials = await CredentialsRepository(session).for_business(business_id)
    if credentials is None:
        raise NotFoundError("Credentials not configured")

    report: dict[str, object] = {"telegram": {"configured": credentials.telegram_ready}}
    if credentials.telegram_ready:
        try:
            publisher = TelegramPublisher(credentials.tg_bot_token)
            report["telegram"] = {
                "configured": True,
                "bot": (await publisher.get_me()).get("username"),
                "channel": (await publisher.check_channel(credentials.tg_channel_id or "")).get("title"),
                "ok": True,
            }
        except Exception as exc:
            report["telegram"] = {"configured": True, "ok": False, "error": str(exc)[:300]}

    report["instagram"] = {"configured": credentials.instagram_ready}
    if credentials.instagram_ready:
        try:
            publisher = InstagramPublisher(credentials.ig_access_token, credentials.ig_account_id)
            info = await publisher.account_info()
            report["instagram"] = {
                "configured": True,
                "ok": True,
                "username": info.get("username"),
                "followers": info.get("followers_count"),
                "quota": await publisher.publishing_limit(),
            }
        except Exception as exc:
            report["instagram"] = {"configured": True, "ok": False, "error": str(exc)[:300]}

    return APIResponse.ok(report)


@router.post("/{business_id}/credentials/refresh-token", response_model=APIResponse[dict])
async def refresh_instagram_token(
    business_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[dict]:
    """Exchange the stored IG token for a fresh long-lived one."""
    from app.services.instagram_publisher import exchange_long_lived_token

    credentials = await CredentialsRepository(session).for_business(business_id)
    if credentials is None or not credentials.ig_access_token:
        raise ConfigurationError("No Instagram token stored for this business")

    token, expires_at = await exchange_long_lived_token(credentials.ig_access_token)
    credentials.ig_access_token = token
    credentials.ig_token_expires_at = expires_at
    await session.flush()
    return APIResponse.ok({"refreshed": True, "expires_at": expires_at.isoformat() if expires_at else None})


# --------------------------------------------------------------------------- #
# Knowledge base
# --------------------------------------------------------------------------- #
@router.get("/{business_id}/knowledge", response_model=APIResponse[KnowledgeBaseRead])
async def get_knowledge(
    business_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[KnowledgeBaseRead]:
    knowledge = await KnowledgeBaseRepository(session).get_or_create(business_id)
    knowledge.compute_completeness()
    return APIResponse.ok(KnowledgeBaseRead.model_validate(knowledge))


@router.put("/{business_id}/knowledge", response_model=APIResponse[KnowledgeBaseRead])
async def update_knowledge(
    business_id: uuid.UUID, payload: KnowledgeBaseUpdate, session: SessionDep, _: AuthDep
) -> APIResponse[KnowledgeBaseRead]:
    repo = KnowledgeBaseRepository(session)
    knowledge = await repo.get_or_create(business_id)
    await repo.update(knowledge, payload.model_dump(exclude_unset=True))
    knowledge.version = (knowledge.version or 0) + 1
    knowledge.compute_completeness()
    return APIResponse.ok(KnowledgeBaseRead.model_validate(knowledge))


@router.post("/{business_id}/knowledge/ingest", response_model=APIResponse[dict])
async def ingest_knowledge(
    business_id: uuid.UUID, payload: dict, session: SessionDep, _: AuthDep
) -> APIResponse[dict]:
    """Feed free-form notes (or a transcript) through the OnboardingAgent."""
    from app.agents.onboarding import OnboardingAgent

    text = str(payload.get("text", "")).strip()
    if not text:
        raise ConfigurationError("`text` is required")

    business = await BusinessRepository(session).get_full_or_404(business_id)
    knowledge = await KnowledgeBaseRepository(session).get_or_create(business_id)
    result = await OnboardingAgent(session=session).ingest(business, knowledge, text, source="api")

    return APIResponse.ok(
        {
            "updated_fields": result.updated_fields,
            "completeness": result.completeness,
            "next_question": result.next_question,
            "summary": result.summary,
        }
    )


@router.post("/{business_id}/knowledge/ingest-file", response_model=APIResponse[dict])
async def ingest_knowledge_file(
    business_id: uuid.UUID,
    session: SessionDep,
    _: AuthDep,
    file: Annotated[UploadFile, File(description="PDF yoki oddiy matn fayli")],
) -> APIResponse[dict]:
    """Feed an uploaded PDF (or plain-text file) through the OnboardingAgent."""
    from app.agents.onboarding import MAX_DOCUMENT_BYTES, OnboardingAgent

    filename = file.filename or "document.pdf"
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValidationError("Fayl juda katta — 12 MB dan oshmasin")
    if not data:
        raise ValidationError("Fayl bo'sh")

    # Trust the bytes, not the client-supplied content type.
    is_pdf = data.startswith(b"%PDF-")
    is_text = filename.lower().endswith((".txt", ".md")) or (file.content_type or "").startswith("text/")
    if not is_pdf and not is_text:
        raise ValidationError("Faqat PDF yoki oddiy matn (.txt, .md) fayllari qabul qilinadi")

    business = await BusinessRepository(session).get_full_or_404(business_id)
    knowledge = await KnowledgeBaseRepository(session).get_or_create(business_id)
    agent = OnboardingAgent(session=session)

    if is_pdf:
        result = await agent.ingest_document(
            business, knowledge, data, mime_type="application/pdf", filename=filename, source="api"
        )
    else:
        text = data.decode("utf-8", errors="replace").strip()
        if not text:
            raise ValidationError("Fayl bo'sh")
        result = await agent.ingest(business, knowledge, text, source="api")

    return APIResponse.ok(
        {
            "filename": filename,
            "updated_fields": result.updated_fields,
            "completeness": result.completeness,
            "next_question": result.next_question,
            "summary": result.summary,
        }
    )


@router.post("/{business_id}/backdrops", response_model=APIResponse[dict])
async def generate_backdrops(
    business_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[dict]:
    """Draw this business its own backdrop library, in its own brand colours.

    Onboarding a client should not wait on a designer or an image quota: six
    motifs are generated from the palette already in the knowledge base.
    """
    from app.services.backdrops import generate_library
    from app.services.brand_assets import business_dir

    business = await BusinessRepository(session).get_full_or_404(business_id)
    knowledge = await KnowledgeBaseRepository(session).get_or_create(business_id)
    target = business_dir(business.id) / "photos"
    written = generate_library(target, knowledge.brand_colors or {}, prefix="bg")

    return APIResponse.ok(
        {
            "business": business.name,
            "count": len(written),
            "folder": str(target.relative_to(target.parents[2])),
            "files": [path.name for path in written],
        }
    )


# --------------------------------------------------------------------------- #
# Admins
# --------------------------------------------------------------------------- #
@router.get("/{business_id}/admins", response_model=APIResponse[list[AdminRead]])
async def list_admins(
    business_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[list[AdminRead]]:
    rows = await AdminRepository(session).for_business(business_id)
    return APIResponse.ok([AdminRead.model_validate(row) for row in rows])


@router.post("/{business_id}/admins", response_model=APIResponse[AdminRead], status_code=status.HTTP_201_CREATED)
async def add_admin(
    business_id: uuid.UUID, payload: AdminCreate, session: SessionDep, _: AuthDep
) -> APIResponse[AdminRead]:
    admin = await AdminRepository(session).upsert(
        business_id,
        payload.telegram_user_id,
        full_name=payload.full_name,
        username=payload.username,
        role=payload.role,
        receives_reviews=payload.receives_reviews,
    )
    return APIResponse.ok(AdminRead.model_validate(admin))


@router.delete("/{business_id}/admins/{admin_id}", response_model=APIResponse[MessageResponse])
async def remove_admin(
    business_id: uuid.UUID, admin_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[MessageResponse]:
    repo = AdminRepository(session)
    admin = await repo.get_or_404(admin_id)
    if admin.business_id != business_id:
        raise NotFoundError("Admin does not belong to this business")
    await repo.delete(admin)
    return APIResponse.ok(MessageResponse(message="Admin removed"))
