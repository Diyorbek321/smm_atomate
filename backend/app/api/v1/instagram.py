"""The Instagram webhook: verification, signature, and a fast hand-off.

Meta retries a slow webhook and eventually disables it, so nothing that can
block happens here — the body is authenticated, queued, and answered 200. The
work is :mod:`app.tasks.instagram`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response, status

from app.core.config import settings
from app.core.logging import get_logger

router = APIRouter(tags=["instagram"])
log = get_logger(__name__)


@router.get("/instagram/webhook", include_in_schema=False)
async def verify_webhook(
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    """Meta's one-time handshake when the webhook is registered.

    An empty `META_VERIFY_TOKEN` refuses the handshake rather than accepting
    any caller: an unconfigured webhook that answers is worse than one that
    does not exist, because it looks connected.
    """
    if not settings.meta_verify_token:
        log.warning("ig_webhook_unconfigured")
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    if hub_mode != "subscribe" or hub_verify_token != settings.meta_verify_token:
        log.warning("ig_webhook_bad_verify_token")
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    return Response(content=hub_challenge or "", media_type="text/plain")


@router.post("/instagram/webhook", include_in_schema=False)
async def receive_webhook(
    request: Request,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> Response:
    """Authenticate, queue, and get out of the way."""
    from app.services.instagram_messaging import parse, verify_signature

    body = await request.body()
    if not verify_signature(body, x_hub_signature_256):
        log.warning("ig_webhook_bad_signature", bytes=len(body))
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = await request.json()
    except Exception:
        log.warning("ig_webhook_bad_json")
        # 200 on purpose: a body we cannot read will not become readable on a
        # retry, and refusing it repeatedly is what gets a webhook disabled.
        return Response(status_code=status.HTTP_200_OK)

    events = [event for event in parse(payload) if event.answerable]
    if not events:
        return Response(status_code=status.HTTP_200_OK)

    from app.tasks.dispatch import enqueue

    for event in events:
        task_id = enqueue(
            "app.tasks.instagram.handle_event",
            event.account_id, event.kind, event.sender_id, event.text,
            comment_id=event.comment_id, username=event.username,
        )
        if not task_id:
            log.error("ig_webhook_no_queue", account=event.account_id)
    return Response(status_code=status.HTTP_200_OK)
