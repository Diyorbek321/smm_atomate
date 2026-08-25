"""Manual generation triggers and publish-now actions."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile

from app.api.deps import AuthDep, SessionDep
from app.core.exceptions import ConflictError
from app.core.logging import get_logger
from app.models.enums import ContentItemStatus
from app.repositories.business import BusinessRepository
from app.repositories.content import ContentItemRepository
from app.schemas.common import APIResponse
from app.schemas.generation import (
    GenerateItemRequest,
    GeneratePlanRequest,
    GenerationTaskResponse,
    PublishNowRequest,
    RegenerateRequest,
)

log = get_logger(__name__)
router = APIRouter(prefix="/generate", tags=["generation"])


def _enqueue(task_path: str, *args: object, **kwargs: object) -> str | None:
    """Send a task to Celery; returns None when the broker is unreachable."""
    from app.tasks.dispatch import enqueue

    return enqueue(task_path, *args, **kwargs)


@router.post("/plan", response_model=APIResponse[GenerationTaskResponse])
async def generate_plan(
    payload: GeneratePlanRequest,
    session: SessionDep,
    _: AuthDep,
    background: BackgroundTasks,
) -> APIResponse[GenerationTaskResponse]:
    """Kick off a full weekly/monthly plan generation.

    Runs on the Celery `generation` queue; falls back to a FastAPI background
    task when no broker is available (single-process deployments).
    """
    await BusinessRepository(session).get_or_404(payload.business_id)

    task_id = _enqueue(
        "app.tasks.generation.generate_weekly_plan",
        str(payload.business_id),
        starts_on=payload.starts_on.isoformat() if payload.starts_on else None,
        horizon_days=payload.horizon_days,
        posts_count=payload.posts_count,
        extra_instructions=payload.extra_instructions,
        send_for_review=payload.send_for_review,
    )

    if task_id is None:
        background.add_task(_inline_plan, payload)
        return APIResponse.ok(
            GenerationTaskResponse(status="running_inline", message="Broker unavailable — running in-process")
        )

    return APIResponse.ok(
        GenerationTaskResponse(task_id=task_id, status="queued", message="Plan generation queued")
    )


async def _inline_plan(payload: GeneratePlanRequest) -> None:
    """Fallback path used when Celery is not reachable."""
    from app.agents.orchestrator import ContentPipeline
    from app.bot.notifier import push_items_for_review, push_plan_summary
    from app.db.session import session_scope

    async with session_scope() as session:
        result = await ContentPipeline(session).generate_plan(
            payload.business_id,
            starts_on=payload.starts_on,
            horizon_days=payload.horizon_days,
            posts_count=payload.posts_count,
            extra_instructions=payload.extra_instructions,
        )
        if payload.send_for_review and result.plan and result.items:
            business = await BusinessRepository(session).get_full_or_404(payload.business_id)
            await push_plan_summary(session, business, result.plan)
            await push_items_for_review(session, business, result.items[:3])


@router.post("/item", response_model=APIResponse[GenerationTaskResponse])
async def generate_item(
    payload: GenerateItemRequest,
    session: SessionDep,
    _: AuthDep,
    background: BackgroundTasks,
) -> APIResponse[GenerationTaskResponse]:
    await BusinessRepository(session).get_or_404(payload.business_id)

    task_id = _enqueue(
        "app.tasks.generation.generate_single_item",
        str(payload.business_id),
        content_type=payload.content_type.value,
        pillar=payload.pillar.value,
        topic=payload.topic,
        platform=payload.platform.value,
        scheduled_at=payload.scheduled_at.isoformat() if payload.scheduled_at else None,
        extra_instructions=payload.extra_instructions,
        render_image=payload.render_image,
        send_for_review=payload.send_for_review,
    )

    if task_id is None:
        background.add_task(_inline_item, payload)
        return APIResponse.ok(GenerationTaskResponse(status="running_inline", message="Generating in-process"))

    return APIResponse.ok(GenerationTaskResponse(task_id=task_id, status="queued", message="Item queued"))


async def _inline_item(payload: GenerateItemRequest) -> None:
    from app.agents.orchestrator import ContentPipeline
    from app.bot.notifier import push_items_for_review
    from app.db.session import session_scope

    async with session_scope() as session:
        item = await ContentPipeline(session).generate_single(
            payload.business_id,
            content_type=payload.content_type,
            pillar=payload.pillar,
            topic=payload.topic,
            platform=payload.platform,
            scheduled_at=payload.scheduled_at,
            extra_instructions=payload.extra_instructions,
            render_image=payload.render_image,
        )
        if payload.send_for_review:
            business = await BusinessRepository(session).get_full_or_404(payload.business_id)
            await push_items_for_review(session, business, [item])


@router.post("/item/{item_id}/regenerate", response_model=APIResponse[GenerationTaskResponse])
async def regenerate_item(
    item_id: uuid.UUID, payload: RegenerateRequest, session: SessionDep, _: AuthDep
) -> APIResponse[GenerationTaskResponse]:
    item = await ContentItemRepository(session).get_or_404(item_id)
    if item.status == ContentItemStatus.PUBLISHED:
        raise ConflictError("Published items cannot be regenerated")

    task_id = _enqueue(
        "app.tasks.generation.regenerate_item",
        str(item_id),
        instruction=payload.instruction,
        regenerate_image=payload.regenerate_image,
    )
    if task_id is None:
        from app.agents.orchestrator import ContentPipeline

        await ContentPipeline(session).regenerate(
            item, instruction=payload.instruction, regenerate_image=payload.regenerate_image
        )
        return APIResponse.ok(
            GenerationTaskResponse(status="done", message="Regenerated", item_ids=[item.id])
        )

    return APIResponse.ok(
        GenerationTaskResponse(task_id=task_id, status="queued", message="Regeneration queued", item_ids=[item_id])
    )


@router.post("/item/{item_id}/publish", response_model=APIResponse[GenerationTaskResponse])
async def publish_now(
    item_id: uuid.UUID, payload: PublishNowRequest, session: SessionDep, _: AuthDep
) -> APIResponse[GenerationTaskResponse]:
    """Publish immediately, bypassing the schedule."""
    item = await ContentItemRepository(session).get_or_404(item_id)
    if item.status == ContentItemStatus.PUBLISHED and not payload.force:
        raise ConflictError("Item is already published (use force=true to repost)")

    task_id = _enqueue("app.tasks.publishing.publish_item", str(item_id), force=payload.force)
    if task_id is None:
        from app.services.publisher import PublishingService

        business = await BusinessRepository(session).get_full_or_404(item.business_id)
        result = await PublishingService(session).publish(item, business, force=payload.force)
        return APIResponse.ok(
            GenerationTaskResponse(
                status=str(item.status),
                message=result.errors or "published",
                item_ids=[item.id],
            )
        )

    return APIResponse.ok(
        GenerationTaskResponse(task_id=task_id, status="queued", message="Publish queued", item_ids=[item_id])
    )


@router.get("/task/{task_id}", response_model=APIResponse[dict])
async def task_status(task_id: str, _: AuthDep) -> APIResponse[dict]:
    try:
        from app.tasks.celery_app import celery_app

        result = celery_app.AsyncResult(task_id)
        return APIResponse.ok(
            {
                "task_id": task_id,
                "state": result.state,
                "ready": result.ready(),
                "result": result.result if result.ready() and result.successful() else None,
                "error": str(result.result) if result.failed() else None,
            }
        )
    except Exception as exc:
        return APIResponse.ok({"task_id": task_id, "state": "UNKNOWN", "error": str(exc)[:200]})


@router.post("/promo", response_model=APIResponse[dict])
async def generate_promo(
    payload: dict, session: SessionDep, _: AuthDep
) -> APIResponse[dict]:
    """Render a browser-drawn promo clip from one of the authored families.

    Always queued: a real browser draws every frame, so even a short clip takes
    longer than a request should wait. `family` forces a specific layout;
    omitted, it is chosen from `pillar`.
    """
    return await _queue_promo(payload, session, "app.tasks.generation.render_promo_clip",
                              "Klip navbatga qo'yildi")


@router.post("/promo-carousel", response_model=APIResponse[dict])
async def generate_promo_carousel(
    payload: dict, session: SessionDep, _: AuthDep
) -> APIResponse[dict]:
    """The same families exported as carousel slides rather than video."""
    return await _queue_promo(payload, session, "app.tasks.generation.render_promo_carousel",
                              "Karusel navbatga qo'yildi")


async def _queue_promo(
    payload: dict, session: SessionDep, task: str, queued_message: str
) -> APIResponse[dict]:
    from app.core.exceptions import ValidationError
    from app.services.promo_families import FAMILIES

    raw_business = str(payload.get("business_id", "")).strip()
    topic = str(payload.get("topic", "")).strip()
    if not raw_business or not topic:
        raise ValidationError("`business_id` va `topic` majburiy")

    family = str(payload.get("family", "")).strip() or None
    if family and family not in FAMILIES:
        raise ValidationError(f"Noma'lum shablon «{family}». Mavjud: {', '.join(FAMILIES)}")
    pillar = str(payload.get("pillar", "educational")).strip()

    business_id = uuid.UUID(raw_business)
    business = await BusinessRepository(session).get_full_or_404(business_id)
    if not business.capabilities.video:
        raise ValidationError(
            f"Promo klip «{business.plan}» tarifiga kirmaydi — Pro tarifi kerak"
        )

    task_id = _enqueue(task, str(business_id), topic=topic, pillar=pillar,
                       family=family, seed=int(payload.get("seed", 0)))
    if not task_id:
        raise ValidationError("Navbat mavjud emas — keyinroq urinib ko'ring")
    return APIResponse.ok({
        "task_id": task_id, "status": "queued", "family": family or f"({pillar} bo'yicha)",
        "message": f"{queued_message} — /generate/task/{{id}} orqali kuzating",
    })


@router.post("/kinetic", response_model=APIResponse[dict])
async def generate_kinetic(
    payload: dict, session: SessionDep, _: AuthDep
) -> APIResponse[dict]:
    """Render a kinetic-typography promo clip.

    `length="short"` (12-18s) renders inline — it is quick enough to answer in
    the request. `length="long"` (~60s) takes minutes, so it goes to the queue
    and the caller polls `/generate/task/{id}` like every other slow job.
    """
    from app.core.exceptions import ValidationError

    raw_business = str(payload.get("business_id", "")).strip()
    topic = str(payload.get("topic", "")).strip()
    length = "long" if str(payload.get("length", "short")).lower() == "long" else "short"
    if not raw_business or not topic:
        raise ValidationError("`business_id` va `topic` majburiy")

    business_id = uuid.UUID(raw_business)
    business = await BusinessRepository(session).get_full_or_404(business_id)
    if not business.capabilities.video:
        raise ValidationError(
            f"Kinetik klip «{business.plan}» tarifiga kirmaydi — Pro tarifi kerak"
        )

    if length == "long":
        task_id = _enqueue(
            "app.tasks.generation.render_kinetic_clip", str(business_id), topic=topic, length=length
        )
        if task_id:
            return APIResponse.ok(
                {"task_id": task_id, "status": "queued", "length": length,
                 "message": "Klip navbatga qo'yildi — /generate/task/{id} orqali kuzating"}
            )
        log.warning("kinetic_broker_unavailable_running_inline")

    from app.agents.kinetic import KineticAgent
    from app.repositories.business import KnowledgeBaseRepository

    knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
    agent = KineticAgent(session=session)
    result = await agent.run(business, knowledge, topic, length=length)
    return APIResponse.ok(
        {
            "video_url": result.video.url,
            "filename": result.video.filename,
            "size": result.video.size,
            "cover_url": result.cover.url if result.cover else None,
            "issues": result.issues,
            "length": length,
            "usage": agent.usage.as_dict(),
        }
    )


@router.post("/kinetic/voiceover", response_model=APIResponse[dict])
async def kinetic_voiceover(
    session: SessionDep,
    _: AuthDep,
    video: Annotated[str, Form(description="Media fayl nomi, masalan 20260821/kinetic-abc.mp4")],
    file: Annotated[UploadFile, File(description="Ovoz yozuvi (mp3/m4a/wav)")],
) -> APIResponse[dict]:
    """Lay a recorded voice over a finished clip, ducking the bed under it."""
    import tempfile
    from pathlib import Path

    from app.core.exceptions import NotFoundError, ValidationError
    from app.services.kinetic import mix_voiceover
    from app.services.storage import get_storage

    root = get_storage().root
    source = (root / video.lstrip("/")).resolve()
    if not str(source).startswith(str(root.resolve())):
        raise ValidationError("Noto'g'ri fayl yo'li")      # no escaping the media root
    if not source.exists():
        raise NotFoundError(f"Video topilmadi: {video}")

    suffix = Path(file.filename or "voice.mp3").suffix.lower() or ".mp3"
    if suffix not in (".mp3", ".m4a", ".wav", ".ogg", ".aac"):
        raise ValidationError("Faqat mp3, m4a, wav, ogg yoki aac qabul qilinadi")

    data = await file.read(60 * 1024 * 1024)
    if not data:
        raise ValidationError("Ovoz fayli bo'sh")

    with tempfile.TemporaryDirectory() as tmp:
        voice_path = Path(tmp) / f"voice{suffix}"
        voice_path.write_bytes(data)
        stored = await mix_voiceover(source, voice_path)

    return APIResponse.ok(
        {"video_url": stored.url, "filename": stored.filename, "size": stored.size}
    )
