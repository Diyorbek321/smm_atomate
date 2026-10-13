"""Health checks, provider status and the Telegram webhook endpoint."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, Response, status
from sqlalchemy import text

from app.api.deps import AuthDep, SessionDep
from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.common import APIResponse

log = get_logger(__name__)

def _reachable(url: str) -> bool:
    """Whether Meta could actually resolve this base URL.

    Not a network check — a name check. `localhost` is Meta's own localhost,
    and every Instagram publish and every webhook delivery fails on it while
    the error text talks about media or subscriptions instead.
    """
    lowered = (url or "").lower()
    if not lowered.startswith("https://"):
        return False
    return not any(host in lowered for host in
                   ("localhost", "127.0.0.1", "0.0.0.0", "::1", ".local"))


#: Root-level, unauthenticated: probes and the Telegram webhook.
router = APIRouter(tags=["system"])
#: Mounted under /api/v1 and protected by the API key.
admin_router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe — intentionally dependency-free and unauthenticated."""
    return {"status": "ok", "app": settings.app_name, "env": settings.env}


@router.get("/health/ready")
async def readiness(session: SessionDep) -> dict[str, Any]:
    """Readiness probe — verifies Postgres and Redis are reachable."""
    checks: dict[str, Any] = {"database": False, "redis": False}

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:
        checks["database_error"] = str(exc)[:200]

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        checks["redis"] = True
    except Exception as exc:
        checks["redis_error"] = str(exc)[:200]

    checks["status"] = "ok" if checks["database"] and checks["redis"] else "degraded"
    return checks


@admin_router.get("/providers", response_model=APIResponse[dict])
async def provider_status(_: AuthDep) -> APIResponse[dict]:
    """Which integrations are configured (no secrets are returned)."""
    from app.services.image_gen import get_image_generator
    from app.services.transcription import get_transcriber

    return APIResponse.ok(
        {
            "gemini": {
                "provider": settings.llm_provider,
                "configured": bool(settings.llm_key),
                "fast_model": settings.llm_model_fast,
                "pro_model": settings.llm_model_pro,
            },
            "images": {
                "provider": settings.image_provider,
                "configured": get_image_generator().enabled,
            },
            "transcription": {
                "provider": settings.transcription_provider,
                "configured": get_transcriber().enabled,
            },
            "telegram_bot": {"configured": bool(settings.telegram_bot_token)},
            "meta": {
                "configured": bool(settings.meta_app_id and settings.meta_app_secret),
                "app_id": bool(settings.meta_app_id),
                "app_secret": bool(settings.meta_app_secret),
                "webhook": bool(settings.meta_verify_token),
                # Named rather than implied. Instagram *pulls* media from this
                # URL and *pushes* webhooks to it, so a localhost value means
                # both directions fail — silently, and for a reason that looks
                # nothing like a networking problem from the Meta error text.
                "reachable_base_url": _reachable(settings.public_base_url),
            },
            "public_base_url": settings.public_base_url,
        }
    )


@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> Response:
    """Receive Telegram updates when TELEGRAM_USE_WEBHOOK=true."""
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        log.warning("webhook_bad_secret")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    dispatcher = getattr(request.app.state, "dispatcher", None)
    bot = getattr(request.app.state, "bot", None)
    if dispatcher is None or bot is None:
        log.error("webhook_without_dispatcher")
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    from aiogram.types import Update

    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dispatcher.feed_update(bot, update)
    return Response(status_code=status.HTTP_200_OK)
