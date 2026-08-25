"""Bot middlewares: DB session per update + admin/business resolution."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.models.business import BusinessAdmin
from app.repositories.business import AdminRepository

log = get_logger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    """Open one transactional session per update and inject it as `session`.

    A custom ``session_factory`` can be supplied so a process (or a test) can
    bind the bot to its own engine.
    """

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory or SessionFactory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = self._session_factory()
        data["session"] = session
        try:
            result = await handler(event, data)
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class AdminContextMiddleware(BaseMiddleware):
    """Resolve which businesses the sender may act on.

    Injects `admins` (all memberships) and `admin` / `business` (the active one).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        session = data.get("session")
        admins: list[BusinessAdmin] = []

        if user is not None and session is not None:
            admins = list(await AdminRepository(session).by_telegram_user(user.id))

        data["admins"] = admins
        active = await self._active(admins, data)
        data["admin"] = active
        data["business"] = active.business if active else None
        data["may_register"] = self._may_register(user)
        return await handler(event, data)

    @staticmethod
    def _may_register(user: User | None) -> bool:
        """Whether this account may create a NEW business from the bot.

        Membership authorises operating a business; it does not authorise
        conjuring one. Without this, any stranger who finds the bot becomes the
        owner of a fresh business and starts spending the account's generation
        budget — and the bot is meant to be public, because that is where leads
        come from.

        An empty `TELEGRAM_ADMIN_IDS` keeps the old open behaviour, which is
        what local development and the test suite expect.
        """
        from app.core.config import settings

        allowlist = settings.admin_ids
        if not allowlist:
            return True
        return user is not None and user.id in allowlist

    @staticmethod
    async def _active(admins: list[BusinessAdmin], data: dict[str, Any]) -> BusinessAdmin | None:
        if not admins:
            return None
        state = data.get("state")
        if state is not None:
            stored = (await state.get_data()).get("active_business_id")
            if stored:
                for admin in admins:
                    if str(admin.business_id) == str(stored):
                        return admin
        return admins[0]


class MenuResetMiddleware(BaseMiddleware):
    """A menu button ends whatever flow the sender was in.

    The persistent keyboard sits under every prompt, so "which topic?" is
    always one tap away from "📊 Holat". The handlers now refuse to swallow a
    button label, but refusing is only half the answer: without this the
    sender still holds `waiting_topic`, and the next thing they type — a real
    topic or not — is consumed by a flow they thought they had left.

    Done here rather than in seven handlers because the next button added
    would be the one nobody remembered to fix.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from app.bot.keyboards import MENU_TEXTS

        state: FSMContext | None = data.get("state")
        text = getattr(event, "text", None)
        if state is not None and text in MENU_TEXTS and await state.get_state() is not None:
            await state.set_state(None)
        return await handler(event, data)


class LoggingMiddleware(BaseMiddleware):
    """Structured access log for every handled update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        user: User | None = data.get("event_from_user")
        kind = "message" if isinstance(event, Message) else "callback" if isinstance(event, CallbackQuery) else "update"
        payload = ""
        if isinstance(event, Message):
            payload = (event.text or event.caption or ("<voice>" if event.voice else ""))[:60]
        elif isinstance(event, CallbackQuery):
            payload = (event.data or "")[:60]

        try:
            return await handler(event, data)
        except Exception as exc:
            log.exception("bot_handler_error", kind=kind, user=user.id if user else None, error=str(exc)[:300])
            raise
        finally:
            log.info(
                "bot_update",
                kind=kind,
                user=user.id if user else None,
                payload=payload,
                ms=int((time.perf_counter() - started) * 1000),
            )
