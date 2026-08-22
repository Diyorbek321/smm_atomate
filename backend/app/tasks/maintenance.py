"""Housekeeping: media retention, stuck items, credential health."""

from __future__ import annotations

import os
from datetime import UTC
from typing import Any

from celery import shared_task

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.enums import ContentItemStatus
from app.repositories.content import ContentItemRepository
from app.services.storage import get_storage
from app.tasks.celery_app import celery_app  # noqa: F401 - registers the app
from app.tasks.runner import run_async

log = get_logger(__name__)


@shared_task(name="app.tasks.maintenance.cleanup_media")
def cleanup_media(older_than_days: int | None = None) -> dict[str, Any]:
    removed = get_storage().cleanup(older_than_days or settings.media_retention_days)
    return {"removed": removed}


@shared_task(name="app.tasks.maintenance.unstick_stale_items")
def unstick_stale_items(older_than_minutes: int = 30) -> dict[str, Any]:
    """Reset items abandoned mid-flight by a crashed worker."""

    async def _run() -> int:
        async with session_scope() as session:
            items = await ContentItemRepository(session).stale_generating(older_than_minutes)
            for item in items:
                if item.status == ContentItemStatus.PUBLISHING:
                    item.status = ContentItemStatus.APPROVED     # safe: publisher is idempotent per attempt
                else:
                    item.status = ContentItemStatus.PENDING_REVIEW
                item.last_error = "recovered from a stalled worker"
            return len(items)

    count = run_async(_run())
    if count:
        log.warning("stale_items_recovered", count=count)
    return {"recovered": count}


@shared_task(name="app.tasks.maintenance.database_health")
def database_health() -> dict[str, Any]:  # pragma: no cover - ops helper
    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            return await ContentItemRepository(session).status_counts()

    return run_async(_run())


@shared_task(name="app.tasks.maintenance.backup_database")
def backup_database(keep: int = 7) -> dict[str, Any]:
    """Dump the database to the media volume and keep the last `keep` copies.

    A client's knowledge base and content queue are the product; losing them to
    a bad migration or a stray DELETE is not recoverable from anywhere else.
    """
    import gzip
    import shutil
    import subprocess
    from datetime import datetime

    binary = shutil.which("pg_dump")
    if binary is None:
        log.warning("backup_skipped_no_pg_dump")
        return {"skipped": "pg_dump is not installed"}

    target = settings.media_root / "backups"
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    path = target / f"{settings.postgres_db}-{stamp}.sql.gz"

    command = [
        binary,
        "--host", settings.postgres_host,
        "--port", str(settings.postgres_port),
        "--username", settings.postgres_user,
        "--no-owner", "--no-privileges",
        settings.postgres_db,
    ]
    environment = {**os.environ, "PGPASSWORD": settings.postgres_password}
    try:
        with gzip.open(path, "wb") as out:
            process = subprocess.run(
                command, capture_output=True, env=environment, timeout=600, check=False,
            )
            if process.returncode != 0:
                path.unlink(missing_ok=True)
                log.error("backup_failed", error=process.stderr[-400:].decode(errors="replace"))
                return {"error": "pg_dump failed"}
            out.write(process.stdout)
    except (OSError, subprocess.SubprocessError) as exc:
        path.unlink(missing_ok=True)
        log.error("backup_crashed", error=str(exc)[:300])
        return {"error": str(exc)[:300]}

    copies = sorted(target.glob(f"{settings.postgres_db}-*.sql.gz"))
    removed = 0
    for old in copies[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
        removed += 1

    size = path.stat().st_size
    log.info("backup_written", file=path.name, size=size, removed=removed)
    return {"file": path.name, "size": size, "removed": removed}
