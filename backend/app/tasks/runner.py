"""Bridge between Celery's synchronous world and our async codebase."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from app.core.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """One persistent loop per worker process (keeps HTTP pools warm)."""
    global _loop
    with _lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
        return _loop


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Execute a coroutine from inside a Celery task."""
    loop = _get_loop()
    if loop.is_running():  # pragma: no cover - defensive, e.g. eager mode in tests
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    return loop.run_until_complete(coro)


def shutdown_loop() -> None:  # pragma: no cover - worker teardown
    global _loop
    with _lock:
        if _loop is not None and not _loop.is_closed():
            try:
                _loop.run_until_complete(_close_clients())
            finally:
                _loop.close()
        _loop = None


async def _close_clients() -> None:  # pragma: no cover
    from app.services.http import close_clients
    from app.services.renderer import close_renderer

    await close_clients()
    await close_renderer()
