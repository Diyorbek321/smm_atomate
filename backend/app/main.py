"""FastAPI application factory — REST API, media server and webhook host."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router, system_router
from app.core.config import settings
from app.core.exceptions import AutoSMMError
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)

DESCRIPTION = """
**AutoSMM AI** — an autonomous SMM employee for local businesses.

* Multi-agent content engine (Strategist → Copywriter → Visual → Editor)
* Telegram approval bot with voice feedback
* Scheduled publishing to Telegram channels and Instagram
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("api")
    settings.media_root.mkdir(parents=True, exist_ok=True)
    log.info("api_starting", env=settings.env, database=settings.async_database_url.split("@")[-1])

    if settings.telegram_use_webhook and settings.telegram_bot_token:
        # Host the bot inside the API process when running in webhook mode.
        from app.bot.main import build_dispatcher, create_bot, setup_webhook

        bot = create_bot()
        dispatcher = build_dispatcher()
        app.state.bot = bot
        app.state.dispatcher = dispatcher
        try:
            await setup_webhook(bot)
        except Exception as exc:
            log.error("webhook_setup_failed", error=str(exc)[:300])

    yield

    from app.services.http import close_clients
    from app.services.renderer import close_renderer

    bot = getattr(app.state, "bot", None)
    if bot is not None:
        await bot.session.close()
    await close_renderer()
    await close_clients()

    from app.db.session import dispose_engine

    await dispose_engine()
    log.info("api_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system_router)
    app.include_router(api_router)

    settings.media_root.mkdir(parents=True, exist_ok=True)
    app.mount(
        settings.media_url_prefix,
        StaticFiles(directory=str(settings.media_root)),
        name="media",
    )

    _register_error_handlers(app)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return {
            "app": settings.app_name,
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health",
        }

    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AutoSMMError)
    async def domain_error(request: Request, exc: AutoSMMError) -> JSONResponse:
        log.warning("domain_error", code=exc.code, path=request.url.path, message=exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # `exc.errors()` can carry raw exception objects in `ctx`; encode them.
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "validation_error",
                    "message": "Invalid request",
                    "details": jsonable_encoder(exc.errors()),
                },
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {"code": f"http_{exc.status_code}", "message": str(exc.detail), "details": None},
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        message = str(exc) if settings.debug else "Internal server error"
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": {"code": "internal_error", "message": message, "details": None}},
        )


app = create_app()
