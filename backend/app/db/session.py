"""Async engine / session factory and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

engine: AsyncEngine = create_async_engine(
    settings.async_database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=1800,
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Transactional scope for workers, the bot and scripts.

    Commits on success, rolls back on any exception, always closes.
    """
    session = SessionFactory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — one session per request."""
    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()
    log.info("db_engine_disposed")
