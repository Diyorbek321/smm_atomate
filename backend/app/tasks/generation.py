"""Background content generation tasks."""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task
from sqlalchemy import select

from app.agents.orchestrator import ContentPipeline
from app.agents.video_editor import VideoEditorAgent, VideoEditRequest
from app.bot.notifier import push_items_for_review, push_plan_summary
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.enums import ContentPillar, ContentType, Platform
from app.repositories.business import BusinessRepository
from app.repositories.content import ContentItemRepository
from app.tasks.celery_app import celery_app  # noqa: F401 - registers the app
from app.tasks.runner import run_async
from app.utils.dates import next_monday, utcnow

log = get_logger(__name__)

#: Preview items pushed alongside the weekly summary card.
PREVIEW_ITEMS = 3


@shared_task(name="app.tasks.generation.generate_weekly_plan", bind=True, max_retries=2, default_retry_delay=300)
def generate_weekly_plan(
    self: Any,
    business_id: str,
    *,
    starts_on: str | None = None,
    horizon_days: int = 7,
    posts_count: int | None = None,
    extra_instructions: str = "",
    send_for_review: bool = True,
) -> dict[str, Any]:
    """Generate (or regenerate) a full content plan for one business."""
    from datetime import date

    start = date.fromisoformat(starts_on) if starts_on else next_monday()

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            pipeline = ContentPipeline(session)
            result = await pipeline.generate_plan(
                uuid.UUID(business_id),
                starts_on=start,
                horizon_days=horizon_days,
                posts_count=posts_count,
                extra_instructions=extra_instructions,
            )
            payload = {
                "plan_id": str(result.plan.id) if result.plan else None,
                "items": len(result.items),
                "failures": result.failures,
                "usage": result.usage.as_dict(),
            }

            if send_for_review and result.plan and result.items:
                business = await BusinessRepository(session).get_full_or_404(uuid.UUID(business_id))
                await push_plan_summary(session, business, result.plan)
                await push_items_for_review(session, business, result.items[:PREVIEW_ITEMS])
            return payload

    try:
        outcome = run_async(_run())
    except Exception as exc:
        log.error("weekly_plan_task_failed", business=business_id, error=str(exc)[:300])
        raise self.retry(exc=exc) from exc

    log.info("weekly_plan_task_done", business=business_id, **{k: v for k, v in outcome.items() if k != "usage"})
    return outcome


@shared_task(name="app.tasks.generation.generate_plans_for_all")
def generate_plans_for_all(horizon_days: int = 7) -> dict[str, Any]:
    """Beat entrypoint: queue a plan for every active business missing one."""

    async def _targets() -> list[str]:
        async with session_scope() as session:
            businesses = await BusinessRepository(session).list_active()
            from app.repositories.content import ContentPlanRepository

            plans = ContentPlanRepository(session)
            start = next_monday()
            covered = set(await plans.businesses_missing_plan(start))
            return [str(b.id) for b in businesses if b.id not in covered]

    targets = run_async(_targets())
    for business_id in targets:
        generate_weekly_plan.delay(business_id, horizon_days=horizon_days)

    log.info("weekly_plans_queued", count=len(targets))
    return {"queued": len(targets), "business_ids": targets}


@shared_task(name="app.tasks.generation.generate_single_item", bind=True, max_retries=2, default_retry_delay=120)
def generate_single_item(
    self: Any,
    business_id: str,
    *,
    content_type: str = ContentType.FEED_POST.value,
    pillar: str = ContentPillar.SALES.value,
    topic: str = "",
    platform: str = Platform.BOTH.value,
    scheduled_at: str | None = None,
    extra_instructions: str = "",
    render_image: bool = True,
    send_for_review: bool = True,
) -> dict[str, Any]:
    from datetime import datetime

    when = datetime.fromisoformat(scheduled_at) if scheduled_at else None

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            item = await ContentPipeline(session).generate_single(
                uuid.UUID(business_id),
                content_type=ContentType(content_type),
                pillar=ContentPillar(pillar),
                topic=topic,
                platform=Platform(platform),
                scheduled_at=when,
                extra_instructions=extra_instructions,
                render_image=render_image,
            )
            if send_for_review:
                business = await BusinessRepository(session).get_full_or_404(uuid.UUID(business_id))
                await push_items_for_review(session, business, [item])
            return {"item_id": str(item.id), "status": str(item.status), "quality": item.quality_score}

    try:
        return run_async(_run())
    except Exception as exc:
        log.error("single_item_task_failed", business=business_id, error=str(exc)[:300])
        raise self.retry(exc=exc) from exc


@shared_task(name="app.tasks.generation.regenerate_item", bind=True, max_retries=1, default_retry_delay=60)
def regenerate_item(
    self: Any,
    item_id: str,
    *,
    instruction: str = "",
    regenerate_image: bool = False,
    notify: bool = True,
) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            repo = ContentItemRepository(session)
            item = await repo.get_or_404(uuid.UUID(item_id))
            await ContentPipeline(session).regenerate(
                item, instruction=instruction, regenerate_image=regenerate_image
            )
            if notify:
                business = await BusinessRepository(session).get_full_or_404(item.business_id)
                await push_items_for_review(session, business, [item])
            return {"item_id": str(item.id), "quality": item.quality_score}

    try:
        return run_async(_run())
    except Exception as exc:
        log.error("regenerate_task_failed", item=item_id, error=str(exc)[:300])
        raise self.retry(exc=exc) from exc


@shared_task(name="app.tasks.generation.send_pending_reviews")
def send_pending_reviews(limit: int = 30) -> dict[str, Any]:
    """Deliver items that were generated but never reached a reviewer."""

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            items = list(await ContentItemRepository(session).unsent_reviews(limit=limit))
            if not items:
                return {"sent": 0, "items": 0}

            by_business: dict[uuid.UUID, list] = {}
            for item in items:
                by_business.setdefault(item.business_id, []).append(item)

            businesses = BusinessRepository(session)
            sent = 0
            for business_id, business_items in by_business.items():
                business = await businesses.get_full(business_id)
                if business is None:
                    continue
                sent += await push_items_for_review(session, business, business_items)
            return {"sent": sent, "items": len(items)}

    outcome = run_async(_run())
    if outcome["items"]:
        log.info("pending_reviews_pushed", **outcome)
    return outcome


@shared_task(name="app.tasks.generation.send_monthly_reports")
def send_monthly_reports() -> dict[str, Any]:
    """Last month's result to every owner, on the 1st, before the new brief.

    Order matters: an owner who has just read that nine people wrote in reads
    the footage request as an investment. The other way round it reads as a
    chore.
    """

    async def _run() -> dict[str, Any]:
        from app.bot.notifier import notify_admins
        from app.services.client_report import build_report, render_telegram

        async with session_scope() as session:
            businesses = await BusinessRepository(session).list_active()
            sent = 0
            for business in businesses:
                try:
                    report = await build_report(session, business)
                    if await notify_admins(session, business.id, render_telegram(report)):
                        sent += 1
                except Exception as exc:
                    log.warning(
                        "monthly_report_failed", business=str(business.id), error=str(exc)[:200]
                    )
            return {"businesses": len(businesses), "sent": sent}

    outcome = run_async(_run())
    log.info("monthly_reports_sent", **outcome)
    return outcome


@shared_task(name="app.tasks.generation.send_shooting_briefs")
def send_shooting_briefs() -> dict[str, Any]:
    """Ask every active owner for this month's footage, on the 1st.

    Sent before the month's planning rather than after: a brief that arrives
    once the calendar is already full gets read as extra homework, and the
    footage it would have produced is what the plan needed in the first place.
    """

    async def _run() -> dict[str, Any]:
        from app.bot.notifier import notify_admins
        from app.repositories.business import KnowledgeBaseRepository
        from app.services.brand_assets import own_footage
        from app.services.shooting_brief import build_brief, render_telegram

        async with session_scope() as session:
            businesses = await BusinessRepository(session).list_active()
            sent = 0
            for business in businesses:
                try:
                    knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
                    brief = build_brief(
                        business, knowledge, footage_on_hand=len(own_footage(business.id))
                    )
                    if await notify_admins(session, business.id, render_telegram(brief)):
                        sent += 1
                except Exception as exc:
                    log.warning(
                        "shooting_brief_failed", business=str(business.id), error=str(exc)[:200]
                    )
            return {"businesses": len(businesses), "sent": sent}

    outcome = run_async(_run())
    log.info("shooting_briefs_sent", **outcome)
    return outcome


@shared_task(name="app.tasks.generation.heartbeat")
def heartbeat() -> dict[str, Any]:  # pragma: no cover - ops helper
    return {"ok": True, "at": utcnow().isoformat()}


@shared_task(name="app.tasks.generation.render_kinetic_clip", bind=True, max_retries=1,
             default_retry_delay=180)
def render_kinetic_clip(
    self: Any, business_id: str, *, topic: str = "", length: str = "long"
) -> dict[str, Any]:
    """Render a kinetic promo off the request thread — a minute takes minutes."""

    async def _run() -> dict[str, Any]:
        from app.agents.kinetic import KineticAgent
        from app.repositories.business import KnowledgeBaseRepository

        async with session_scope() as session:
            business = await BusinessRepository(session).get_full_or_404(uuid.UUID(business_id))
            knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
            agent = KineticAgent(session=session)
            result = await agent.run(business, knowledge, topic, length=length)
            return {
                "video_url": result.video.url,
                "filename": result.video.filename,
                "size": result.video.size,
                "cover_url": result.cover.url if result.cover else None,
                "issues": result.issues,
                "usage": agent.usage.as_dict(),
            }

    try:
        return run_async(_run())
    except Exception as exc:
        log.error("kinetic_task_failed", business=business_id, error=str(exc)[:300])
        raise self.retry(exc=exc) from exc


@shared_task(name="app.tasks.generation.edit_uploaded_video", bind=True, max_retries=1,
             default_retry_delay=120)
def edit_uploaded_video(
    self: Any, business_id: str, source_filename: str, *, caption: str = "", chat_id: int | None = None
) -> dict[str, Any]:
    """Polish footage the owner sent, then queue it for approval like any post.

    Runs off the bot thread: a minute of video takes about a minute of ffmpeg,
    which would otherwise block every other update.
    """
    try:
        return run_async(run_video_edit(business_id, source_filename, caption=caption, chat_id=chat_id))
    except Exception as exc:
        log.error("video_edit_task_failed", business=business_id, error=str(exc)[:300])
        raise self.retry(exc=exc) from exc


async def _transcribe_source(source: bytes) -> tuple[list[dict[str, Any]], float]:
    """Whisper the raw upload, before anything has been cut out of it.

    The subtitle pass inside ``edit_video`` transcribes the *finished* clip, so
    its timestamps describe a timeline that does not exist yet. Deciding what
    to keep needs the opposite: timings against the file as it was uploaded.
    """
    import tempfile
    from pathlib import Path

    from app.services.transcription import get_transcriber
    from app.services.video_editor import extract_audio, probe

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        raw = work / "source.mp4"
        raw.write_bytes(source)

        info = await probe(raw)
        if not info.has_audio:
            return [], info.duration

        audio = work / "speech.m4a"
        if not await extract_audio(raw, audio):
            return [], info.duration

        segments = await get_transcriber().transcribe_segments(
            audio.read_bytes(), filename="speech.m4a", language="uz"
        )
        return list(segments), info.duration


async def plan_cut(
    session: Any, business: Any, source: bytes, *, topic: str = ""
) -> list[tuple[float, float]] | None:
    """What the video editor agent decided to keep, or None to trim silence.

    None is not a failure signal so much as the default: the deterministic
    silence trim is what this pipeline did before the agent existed, and every
    way the agent can be unavailable lands back on it.
    """
    if not settings.use_video_editor_agent:
        return None

    try:
        segments, duration = await _transcribe_source(source)
    except Exception as exc:  # a cut is not worth failing an edit
        log.warning("video_plan_transcribe_failed", error=str(exc)[:200])
        return None

    if not segments:
        # Silent footage, or nothing recognised — there is nothing to reason
        # about, and the agent would only answer with an empty plan.
        return None

    plan = await VideoEditorAgent(session=session).run(
        VideoEditRequest(business=business, segments=segments, duration=duration, topic=topic)
    )
    if not plan.is_usable:
        return None

    log.info(
        "video_cut_planned",
        business=str(business.id),
        kept=plan.total_seconds,
        source=round(duration, 1),
        dropped=len(plan.drop),
    )
    return [(segment.start, segment.end) for segment in plan.keep]


async def run_video_edit(
    business_id: str, source_filename: str, *, caption: str = "", chat_id: int | None = None
) -> dict[str, Any]:
    """The edit itself — awaited directly when there is no broker to queue on."""
    from app.agents.visual import logo_data_uri
    from app.repositories.business import KnowledgeBaseRepository
    from app.services.renderer import merge_colors
    from app.services.storage import get_storage
    from app.services.video_editor import EditSettings, edit_video

    storage = get_storage()
    source_path = storage.root / source_filename
    if not source_path.is_file():
        raise FileNotFoundError(f"uploaded video is gone: {source_filename}")

    async with session_scope() as session:
        business = await BusinessRepository(session).get_full_or_404(uuid.UUID(business_id))
        if not business.capabilities.video_editing:
            return {"skipped": "video editing is not part of this plan"}

        knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
        colours = merge_colors(knowledge.brand_colors if knowledge else None)

        logo: bytes | None = None
        data_uri = logo_data_uri(knowledge)
        if data_uri:
            import base64

            logo = base64.b64decode(data_uri.split(",", 1)[1])

        contact = " · ".join(filter(None, [knowledge.phone or "", knowledge.address or ""]))
        raw = source_path.read_bytes()
        keep = await plan_cut(session, business, raw, topic=caption)
        video, poster, report = await edit_video(
            raw,
            colours=colours,
            logo=logo,
            business_name=business.name,
            contact=contact,
            settings_=EditSettings(),
            language=str(business.language),
            keep=keep,
        )

        stored = storage.save_bytes(video, prefix="edited", content_type="video/mp4")
        poster_url = None
        if poster:
            poster_url = storage.save_bytes(poster, prefix="edited-cover", content_type="image/jpeg").url

        item = await _video_item(session, business, stored.url, poster_url, caption, report)
        await session.flush()

        await push_items_for_review(session, business, [item])

        with contextlib.suppress(OSError):
            source_path.unlink()          # the raw upload is not needed again

        return {
            "item_id": str(item.id),
            "video_url": stored.url,
            "cover_url": poster_url,
            "source_seconds": report.source_seconds,
            "final_seconds": report.final_seconds,
            "trimmed_seconds": report.trimmed_seconds,
            "subtitle_lines": report.subtitle_lines,
            "stages": report.stages,
            "skipped": report.skipped,
            "chat_id": chat_id,
        }




async def _video_item(session: Any, business: Any, video_url: str, cover_url: str | None,
                      caption: str, report: Any) -> Any:
    """Wrap the edited clip in a ContentItem so the usual review flow applies."""
    from app.core.config import settings
    from app.models.content_item import ContentItem
    from app.models.enums import ContentItemStatus, ContentPillar, ContentType, Platform

    # Same rule as every other generated item: straight to the queue unless
    # the client has asked for hands-off publishing.
    auto_approve = business.auto_approve or settings.auto_approve
    topic = (caption or "").strip() or f"{business.name} — video"
    item = ContentItem(
        business_id=business.id,
        content_type=ContentType.VIDEO_POST,
        pillar=ContentPillar.SOCIAL_PROOF,
        platform=Platform.TELEGRAM,
        topic=topic[:300],
        headline=topic[:300],
        hook="",
        cta="",
        caption_tg=(caption or "").strip(),
        caption_ig=(caption or "").strip(),
        hashtags=[],
        video_url=video_url,
        image_url=cover_url,
        status=ContentItemStatus.APPROVED if auto_approve else ContentItemStatus.PENDING_REVIEW,
        scheduled_at=await _next_free_slot(session, business),
        quality_score=0.0,
        editor_report={
            "source": "video_editor",
            "stages": report.stages,
            "skipped": report.skipped,
            "subtitle_lines": report.subtitle_lines,
        },
    )
    session.add(item)
    return item


async def _next_free_slot(session: Any, business: Any) -> datetime:
    """The next posting hour that does not already hold something."""
    from zoneinfo import ZoneInfo

    from app.models.content_item import ContentItem

    tz = ZoneInfo(business.timezone or "UTC")
    taken = {
        row.astimezone(tz).replace(minute=0, second=0, microsecond=0)
        for row in (
            await session.execute(
                select(ContentItem.scheduled_at).where(
                    ContentItem.business_id == business.id,
                    ContentItem.scheduled_at >= utcnow(),
                )
            )
        ).scalars()
    }

    cursor = utcnow().astimezone(tz).replace(minute=0, second=0, microsecond=0)
    hours = sorted(business.posting_hours)
    for day in range(14):
        for hour in hours:
            candidate = (cursor + timedelta(days=day)).replace(hour=hour)
            if candidate <= cursor or candidate in taken:
                continue
            return candidate.astimezone(UTC)
    return (cursor + timedelta(days=1)).astimezone(UTC)


@shared_task(name="app.tasks.generation.render_brand_props", bind=True, max_retries=1, default_retry_delay=600)
def render_brand_props(self: Any, business_id: str, count: int = 6) -> dict[str, Any]:
    """Fill a business's 3D prop shelf — once, when onboarding finishes.

    Kinetic clips built only from type read as captions. One rendered object
    per scene is what the reference work does, and generating them per business
    (in the brand accent, on the shelf its topic looks up first) is what keeps
    two clients from sharing a visual identity.

    Best effort by design: the shelf being empty costs quality, never a clip.
    """
    from app.services.brand_props import ensure_props

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            from app.repositories.business import KnowledgeBaseRepository

            knowledge = await KnowledgeBaseRepository(session).for_business(uuid.UUID(business_id))
            colors = dict(knowledge.brand_colors) if knowledge and knowledge.brand_colors else {}
            # `shelf_for` scans this for keywords, so what the business actually
            # sells decides which objects it gets.
            offerings = knowledge.key_offerings if knowledge else []
            topic = " ".join(
                str(item.get("name") or item.get("title") or "")
                for item in offerings
                if isinstance(item, dict)
            )

        paths = await ensure_props(
            business_id,
            accent=colors.get("accent") or "#4F8CFF",
            topic=topic,
            count=count,
        )
        return {"business_id": business_id, "props": len(paths)}

    try:
        return run_async(_run())
    except Exception as exc:                      # a prop shelf is never worth a retry storm
        log.warning("brand_props_task_failed", business=business_id, error=str(exc)[:300])
        return {"business_id": business_id, "props": 0, "error": str(exc)[:200]}


@shared_task(name="app.tasks.generation.render_promo_clip", bind=True, max_retries=1, default_retry_delay=180)
def render_promo_clip(
    self: Any,
    business_id: str,
    topic: str,
    *,
    pillar: str = "educational",
    family: str | None = None,
    seed: int = 0,
    notify: bool = True,
) -> dict[str, Any]:
    """Write and render one browser-rendered promo clip.

    The heavier of the two video paths: a real browser draws every frame, which
    buys the blend modes, masks and split layouts Pillow cannot do cheaply. Use
    it for hero pieces; :func:`render_kinetic_clip` still carries daily volume.
    """
    from app.agents.promo import PromoAgent
    from app.models.enums import ContentPillar
    from app.services.brand_assets import footage_library, prop_library
    from app.services.promo import render_promo

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            from app.repositories.business import BusinessRepository, KnowledgeBaseRepository

            business = await BusinessRepository(session).get(uuid.UUID(business_id))
            if business is None:
                raise ValueError(f"business {business_id} not found")
            knowledge = await KnowledgeBaseRepository(session).for_business(business.id)
            props = [str(path) for path in prop_library(business.id, topic)]
            clips = [str(path) for path in footage_library(business.id)]
            written = await PromoAgent(session=session).write(
                business, knowledge, topic,
                pillar=ContentPillar(pillar), family=family, props=props,
                footage=clips[seed % len(clips)] if clips else None, seed=seed,
            )

        result = await render_promo(written.script, prefix=f"promo-{written.family}")
        if notify:
            async with session_scope() as session:
                from app.bot.notifier import push_clip

                await push_clip(session, uuid.UUID(business_id), str(result.video.path),
                                caption=f"🎬 {topic}")
        return {
            "business_id": business_id,
            "family": written.family,
            "seconds": result.seconds,
            "video": result.video.filename,
            "cover": result.cover.filename if result.cover else None,
            "issues": result.issues,
        }

    try:
        return run_async(_run())
    except Exception as exc:
        log.warning("promo_clip_failed", business=business_id, error=str(exc)[:300])
        raise self.retry(exc=exc) from exc


@shared_task(name="app.tasks.generation.render_promo_carousel", bind=True, max_retries=1, default_retry_delay=180)
def render_promo_carousel(
    self: Any,
    business_id: str,
    topic: str,
    *,
    pillar: str = "educational",
    family: str | None = None,
    seed: int = 0,
    notify: bool = True,
) -> dict[str, Any]:
    """The same authored families, exported as carousel slides instead of video.

    Carousels are posted about as often as feed images here, so every layout
    improvement should land in both places rather than only in the clips.
    """
    from app.agents.promo import PromoAgent
    from app.models.enums import ContentPillar
    from app.services.brand_assets import footage_library, prop_library
    from app.services.promo import render_carousel

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            from app.repositories.business import BusinessRepository, KnowledgeBaseRepository

            business = await BusinessRepository(session).get(uuid.UUID(business_id))
            if business is None:
                raise ValueError(f"business {business_id} not found")
            knowledge = await KnowledgeBaseRepository(session).for_business(business.id)
            props = [str(path) for path in prop_library(business.id, topic)]
            clips = [str(path) for path in footage_library(business.id)]
            written = await PromoAgent(session=session).write(
                business, knowledge, topic,
                pillar=ContentPillar(pillar), family=family, props=props,
                footage=clips[seed % len(clips)] if clips else None, seed=seed,
            )

        result = await render_carousel(written.script, prefix=f"kar-{written.family}")
        if notify:
            async with session_scope() as session:
                from app.bot.notifier import push_slides

                await push_slides(session, uuid.UUID(business_id),
                                  [str(slide.path) for slide in result.slides],
                                  caption=f"🖼 {topic}")
        return {
            "business_id": business_id,
            "family": written.family,
            "slides": [slide.filename for slide in result.slides],
            "issues": result.issues,
        }

    try:
        return run_async(_run())
    except Exception as exc:
        log.warning("promo_carousel_failed", business=business_id, error=str(exc)[:300])
        raise self.retry(exc=exc) from exc
