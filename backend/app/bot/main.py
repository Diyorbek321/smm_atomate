"""Aiogram 3 bot: dispatcher wiring, polling runner and webhook helpers."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.handlers import build_router
from app.bot.middlewares import (
    AdminContextMiddleware,
    DatabaseMiddleware,
    LoggingMiddleware,
    MenuResetMiddleware,
)
from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)

#: Videos go up at roughly 50 KB/s from here, so a 20 MB clip needs minutes.
UPLOAD_TIMEOUT_SEC = 900.0

BOT_COMMANDS = [
    ("start", "Boshlash"),
    ("plan", "Haftalik reja yaratish"),
    ("review", "Tasdiqlanmagan postlar"),
    ("quick", "Tezkor post"),
    ("klip", "Promo klip"),
    ("footage", "Video kadr javoni"),
    ("kb", "Bilim bazasi"),
    ("status", "Statistika"),
    ("help", "Yordam"),
    ("cancel", "Bekor qilish"),
]


def create_bot(token: str | None = None) -> Bot:
    """Build a Bot with HTML parse mode enabled by default.

    When `TELEGRAM_API_BASE` points at a self-hosted Bot API server the bot
    talks to that instead of api.telegram.org, which lifts the 20 MB download
    cap to 2 GB — the difference between accepting phone footage and not.
    """
    resolved = token or settings.telegram_bot_token
    if not resolved:
        raise ConfigurationError("TELEGRAM_BOT_TOKEN is not configured")

    api = None
    if settings.telegram_api_base:
        base = settings.telegram_api_base.rstrip("/")
        api = TelegramAPIServer(
            base=f"{base}/bot{{token}}/{{method}}",
            file=f"{base}/file/bot{{token}}/{{path}}",
            is_local=True,
        )
        log.info("bot_api_server", base=base)

    # Review cards carry the edited clips, and a 15 MB upload on a slow uplink
    # runs well past aiogram's 60-second default.
    session = AiohttpSession(timeout=UPLOAD_TIMEOUT_SEC, **({"api": api} if api else {}))

    return Bot(
        token=resolved,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )


@contextlib.asynccontextmanager
async def bot_session(token: str | None = None) -> AsyncIterator[Bot]:
    """Short-lived bot instance for workers that only need to send a message."""
    bot = create_bot(token)
    try:
        yield bot
    finally:
        await bot.session.close()


def build_dispatcher(storage: Any = None, session_factory: Any = None) -> Dispatcher:
    """Dispatcher with FSM storage (Redis when available) and middlewares.

    ``storage`` and ``session_factory`` exist so tests (or an embedded runner)
    can supply in-memory state and their own database engine.
    """
    if storage is None:
        try:
            storage = RedisStorage.from_url(settings.redis_url)
            log.info("bot_fsm_storage", backend="redis")
        except Exception as exc:
            log.warning("bot_fsm_storage_fallback_memory", error=str(exc)[:200])
            storage = MemoryStorage()

    dispatcher = Dispatcher(storage=storage)

    # Order: logging → session → admin context (needs the session) →
    # menu reset (needs the FSM context aiogram injects before inner
    # middlewares, so it must not be an outer one).
    for middleware in (
        LoggingMiddleware(),
        DatabaseMiddleware(session_factory),
        AdminContextMiddleware(),
        MenuResetMiddleware(),
    ):
        dispatcher.message.middleware(middleware)
        dispatcher.callback_query.middleware(middleware)

    dispatcher.include_router(build_router())
    return dispatcher


async def set_commands(bot: Bot) -> None:
    from aiogram.types import BotCommand

    await bot.set_my_commands([BotCommand(command=name, description=desc) for name, desc in BOT_COMMANDS])


async def run_polling() -> None:
    configure_logging("bot")
    bot = create_bot()
    dispatcher = build_dispatcher()

    await bot.delete_webhook(drop_pending_updates=True)
    await set_commands(bot)
    me = await bot.get_me()
    log.info("bot_started", mode="polling", username=me.username)

    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()


async def setup_webhook(bot: Bot) -> None:
    if not settings.telegram_webhook_url:
        raise ConfigurationError("TELEGRAM_WEBHOOK_URL is required when TELEGRAM_USE_WEBHOOK=true")
    await bot.set_webhook(
        url=settings.telegram_webhook_url,
        secret_token=settings.telegram_webhook_secret or None,
        drop_pending_updates=True,
    )
    await set_commands(bot)
    log.info("bot_started", mode="webhook", url=settings.telegram_webhook_url)


def main() -> None:  # pragma: no cover - process entrypoint
    try:
        asyncio.run(run_polling())
    except (KeyboardInterrupt, SystemExit):
        log.info("bot_stopped")


if __name__ == "__main__":  # pragma: no cover
    main()
