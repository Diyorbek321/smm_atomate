"""Connect a business's Telegram channel from the dashboard.

``GET`` names the bot to add, ``POST`` checks the channel live and, when the
bot can publish there, saves it — with the discussion group when comments can
be answered too. The checks are :mod:`app.services.telegram_connect`.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AuthDep, BusinessDep, SessionDep
from app.core.config import settings
from app.core.exceptions import ConfigurationError, ConflictError
from app.repositories.business import CredentialsRepository
from app.schemas.common import APIResponse

router = APIRouter(prefix="/businesses", tags=["telegram-connect"])


class ConnectRequest(BaseModel):
    channel: str = Field(min_length=1, max_length=200)


def _token(stored: str | None) -> str:
    token = stored or settings.telegram_bot_token
    if not token or ":" not in token:
        raise ConfigurationError("No Telegram bot token: set TELEGRAM_BOT_TOKEN")
    return token


@router.get("/{business_id}/telegram/bot", response_model=APIResponse[dict])
async def connect_bot(business: BusinessDep, session: SessionDep, _: AuthDep) -> APIResponse[dict]:
    """The bot the admin has to add to the channel and its discussion group."""
    from app.services.telegram_publisher import TelegramPublisher

    credentials = await CredentialsRepository(session).for_business(business.id)
    me = await TelegramPublisher(_token(credentials and credentials.tg_bot_token)).get_me()
    return APIResponse.ok({"username": me.get("username", ""), "id": me.get("id")})


@router.post("/{business_id}/telegram/connect", response_model=APIResponse[dict])
async def connect_channel(
    payload: ConnectRequest, business: BusinessDep, session: SessionDep, _: AuthDep
) -> APIResponse[dict]:
    from app.services.telegram_connect import check_channel
    from app.services.telegram_publisher import TelegramPublisher

    repo = CredentialsRepository(session)
    credentials = await repo.get_or_create(business.id)
    token = _token(credentials.tg_bot_token)
    result = await check_channel(
        TelegramPublisher(token), payload.channel, bot_id=int(token.split(":", 1)[0])
    )

    if result.ok:
        owner = await repo.business_for_channel(
            chat_id=result.channel_id, username=result.username or None
        )
        if owner is not None and owner != business.id:
            raise ConflictError("This channel is already connected to another business")
        # Set directly: `update` skips None, and a stale group must be cleared.
        credentials.tg_discussion_chat_id = result.discussion_id or None
        await repo.update(credentials, {
            "tg_bot_token": token,
            "tg_channel_id": result.channel_id,
            "telegram_enabled": True,
        })

    return APIResponse.ok({
        "ok": result.ok,
        "comments_ok": result.comments_ok,
        "saved": result.ok,
        "channel_id": result.channel_id,
        "title": result.title,
        "username": result.username,
        "discussion_id": result.discussion_id,
        "steps": [asdict(step) for step in result.steps],
    })
