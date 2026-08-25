"""Bot routers, composed in priority order."""

from aiogram import Router

from app.bot.handlers import (
    admin,
    lead,
    onboarding,
    reactions,
    review,
    start,
    video,
    voice,
)

#: Order matters: specific flows first, the catch-all last.
HANDLER_ROUTERS = (
    start.router,
    review.router,
    onboarding.router,
    admin.router,
    video.router,
    lead.router,
    voice.router,
    reactions.router,
)


def _detach(router: Router) -> Router:
    """Allow a module-level router to be attached to a new parent.

    Handlers are declared with decorators on module-level `Router` objects, so
    a second `build_router()` call (a test, a webhook + polling process, a
    second bot) would otherwise fail with "Router is already attached".
    Handlers themselves are stateless — FSM state lives in the storage — so
    re-parenting is safe.
    """
    router._parent_router = None
    return router


def build_router() -> Router:
    """Compose a fresh root router containing every handler module."""
    root = Router(name="root")
    for router in HANDLER_ROUTERS:
        root.include_router(_detach(router))
    return root


__all__ = ["HANDLER_ROUTERS", "build_router"]
