"""The webhook a business's own Telegram bot delivers to.

Same contract as :mod:`app.api.v1.instagram`: authenticate, queue, answer 200.
Telegram retries a failing webhook and queues everything behind it, so nothing
slow happens here. The work is :mod:`app.tasks.telegram_chat`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, status

from app.core.logging import get_logger

router = APIRouter(tags=["telegram-chat"])
log = get_logger(__name__)


@router.post("/telegram/chat/{business_id}/webhook", include_in_schema=False)
async def receive_update(
    business_id: str,
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> Response:
    from app.services.telegram_chat import parse_update, verify_secret

    try:
        business_uuid = uuid.UUID(business_id)
    except ValueError:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    # The URL is guessable; the secret is what proves Telegram sent it.
    if not verify_secret(business_uuid, x_telegram_bot_api_secret_token):
        log.warning("tg_chat_bad_secret", business=business_id)
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        update = await request.json()
    except Exception:
        # 200 on purpose: an unreadable body stays unreadable on every retry.
        log.warning("tg_chat_bad_json", business=business_id)
        return Response(status_code=status.HTTP_200_OK)

    event = parse_update(update)
    if event is None:
        return Response(status_code=status.HTTP_200_OK)

    from app.tasks.dispatch import enqueue

    if not enqueue("app.tasks.telegram_chat.handle_update", str(business_uuid), event.to_task()):
        log.error("tg_chat_no_queue", business=business_id)
    return Response(status_code=status.HTTP_200_OK)
