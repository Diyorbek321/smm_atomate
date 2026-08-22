"""Test fixtures.

DB-backed tests need PostgreSQL; they are skipped when it is unreachable.
Each test gets its own NullPool engine so asyncpg never crosses event loops.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "55432")
os.environ.setdefault("POSTGRES_USER", "autosmm")
os.environ.setdefault("POSTGRES_PASSWORD", "autosmm")
os.environ.setdefault("POSTGRES_DB", "autosmm")
os.environ["LLM_PROVIDER"] = "gemini"   # pin: .env may select another provider
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("IMAGE_PROVIDER", "none")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")


def _pin_default_event_loop_policy() -> None:
    """Neutralise aiogram's global uvloop installation for the test session.

    ``import aiogram`` calls ``uvloop.install()``, and uvloop's policy refuses
    ``asyncio.get_event_loop()`` outside a running loop — which pytest-asyncio
    depends on. Import everything that pulls aiogram in up front, then restore
    the default policy so every test runs under identical conditions. This only
    affects tests; in production uvloop is exactly what we want.
    """
    import asyncio

    import app.bot.main
    import app.tasks.generation
    import app.tasks.maintenance
    import app.tasks.publishing  # noqa: F401

    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())


_pin_default_event_loop_policy()


@pytest.fixture(autouse=True)
def fast_card_renderer(request):
    """Render cards with Pillow unless a test asks for real Chromium.

    Launching a browser per test (each pytest test owns its own event loop)
    would dominate the runtime; the Pillow path exercises the same call chain
    and still produces a real PNG. Mark a test with `@pytest.mark.chromium`
    to use the browser.
    """
    from app.services.renderer import get_renderer

    renderer = get_renderer()
    previous = renderer._unavailable
    if not request.node.get_closest_marker("chromium"):
        renderer._unavailable = True
    yield
    renderer._unavailable = previous


@pytest.fixture(scope="session")
def database() -> bool:
    """Create the schema once, using a *synchronous* engine (no event loop).

    Tests NEVER touch the real database: whatever ``POSTGRES_DB`` says, the
    suite renames it to ``<name>_test`` and creates that database on demand.
    (The dev database was once polluted with hundreds of Test Academy rows and
    a create_all that broke a later migration — this guard is the lesson.)
    """
    from sqlalchemy import create_engine, text

    import app.models  # noqa: F401 - registers every table
    from app.core.config import settings
    from app.db.base import Base

    if not settings.postgres_db.endswith("_test"):
        settings.postgres_db = f"{settings.postgres_db}_test"

    try:
        admin_url = settings.sync_database_url.rsplit("/", 1)[0] + "/postgres"
        admin = create_engine(
            admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
        )
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": settings.postgres_db},
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{settings.postgres_db}"'))
        admin.dispose()

        engine = create_engine(settings.sync_database_url, connect_args={"connect_timeout": 3})
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not reachable: {exc}")

    yield True
    engine.dispose()


@pytest.fixture
async def db_engine(database: bool):
    """A fresh engine per test, pinned to that test's event loop."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings

    engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def session_factory(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def session(session_factory) -> AsyncIterator:
    async with session_factory() as db:
        yield db
        await db.rollback()


@pytest.fixture
async def client(session_factory) -> AsyncIterator:
    """HTTP client with the DB dependency pointed at the per-test engine."""
    from httpx import ASGITransport, AsyncClient

    from app.db.session import get_session
    from app.main import create_app

    app = create_app()

    async def override_session():
        async with session_factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_session] = override_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "test-api-key"},
    ) as http_client:
        yield http_client

    app.dependency_overrides.clear()


@pytest.fixture
def business_payload() -> dict:
    return {
        "name": f"Test Academy {uuid.uuid4().hex[:6]}",
        "category": "education",
        "tone_of_voice": "casual",
        "target_audience": "18-30 yosh, IELTS topshirmoqchi",
        "language": "uz",
        "timezone": "Asia/Tashkent",
        "settings": {"posts_per_week": 8, "posting_hours": [9, 13, 18]},
    }


@pytest.fixture
def patch_global_session_scope(monkeypatch):
    """Point `app.db.session.session_scope` at a per-call NullPool engine.

    Background tasks and Celery workers use the module-level engine, which in
    production lives on a single event loop. Tests run one loop per test, so the
    shared pool would hand connections to the wrong loop.
    """
    import contextlib

    @contextlib.asynccontextmanager
    async def scope():
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from app.core.config import settings

        engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        db = factory()
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()
            await engine.dispose()

    monkeypatch.setattr("app.db.session.session_scope", scope)
    return scope
