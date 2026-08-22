"""Structured logging setup shared by the API, workers and the bot."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import settings

_CONFIGURED = False


def configure_logging(service: str = "api") -> None:
    """Idempotently configure stdlib logging + structlog."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    for noisy in ("httpx", "httpcore", "aiogram.event", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    renderer: Any = (
        structlog.dev.ConsoleRenderer(colors=not settings.is_production)
        if not settings.is_production
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)
    _CONFIGURED = True


def get_logger(name: str) -> Any:
    configure_logging()
    return structlog.get_logger(name)
