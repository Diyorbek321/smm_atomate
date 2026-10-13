"""Moving leads into the client's CRM.

`sync_lead` runs the moment a lead gets a phone number; `sync_pending` sweeps
whatever that missed — a CRM that was down, a worker that restarted, and on
the first run every lead that predates the integration.

The row lock is the whole duplicate story: the per-lead task and the sweep can
reach the same lead at once, and a sales team calling one person twice because
the CRM shows them twice is exactly what this integration exists to prevent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from celery import shared_task
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.lead import Lead
from app.tasks.celery_app import celery_app  # noqa: F401 - registers the app
from app.tasks.runner import run_async

log = get_logger(__name__)

#: After this many failures a lead stops being retried and waits for a human:
#: ten tries over the sweep interval is well past any outage worth waiting on.
MAX_ATTEMPTS = 10
SWEEP_BATCH = 50


def enqueue_sync(lead_id: uuid.UUID | str | None) -> None:
    """Queue a push for a lead that just got a phone. The sweep is the fallback."""
    if lead_id is None:
        return
    from app.tasks.dispatch import enqueue

    enqueue("app.tasks.crm.sync_lead", str(lead_id))


@shared_task(name="app.tasks.crm.sync_lead", bind=True, max_retries=0)
def sync_lead(self: Any, lead_id: str) -> dict[str, Any]:
    try:
        return run_async(_sync(uuid.UUID(lead_id)))
    except Exception as exc:
        log.warning("crm_sync_crashed", lead=lead_id, error=str(exc)[:250])
        return {"synced": False, "reason": "error"}


@shared_task(name="app.tasks.crm.sync_pending")
def sync_pending() -> dict[str, Any]:
    async def _run() -> list[uuid.UUID]:
        async with session_scope() as session:
            from app.models.business import Business

            # Only businesses that opted in: otherwise a client without a CRM
            # fills every batch with leads that can never leave.
            stmt = (
                select(Lead.id)
                .join(Business, Business.id == Lead.business_id)
                .where(
                    Business.settings["crm"]["push"].as_boolean().is_(True),
                    Lead.crm_synced_at.is_(None),
                    Lead.crm_attempts < MAX_ATTEMPTS,
                    Lead.phone != "",
                    Lead.business_id.is_not(None),
                )
                .order_by(Lead.created_at)
                .limit(SWEEP_BATCH)
            )
            return list((await session.execute(stmt)).scalars())

    ids = run_async(_run())
    results = [run_async(_sync(lead_id)) for lead_id in ids]
    synced = sum(1 for r in results if r.get("synced"))
    if ids:
        log.info("crm_sweep", checked=len(ids), synced=synced)
    return {"checked": len(ids), "synced": synced}


async def _sync(lead_id: uuid.UUID) -> dict[str, Any]:
    from app.repositories.business import BusinessRepository
    from app.services.crm import CrmError, crm_config, fetch_catalog, push_lead

    async with session_scope() as session:
        stmt = select(Lead).where(Lead.id == lead_id).with_for_update(skip_locked=True)
        lead = (await session.execute(stmt)).scalars().one_or_none()
        if lead is None:
            # Not committed yet, or another worker holds it. The sweep comes back.
            return {"synced": False, "reason": "busy_or_missing"}
        if lead.crm_synced_at is not None:
            return {"synced": True, "reason": "already"}
        if not lead.phone or lead.business_id is None:
            return {"synced": False, "reason": "no_phone"}

        business = await BusinessRepository(session).get(lead.business_id)
        cfg = crm_config(business) if business else None
        if cfg is None or not cfg.push:
            return {"synced": False, "reason": "crm_off"}

        catalog = await fetch_catalog(cfg)
        try:
            await push_lead(lead, cfg, catalog.courses)
        except CrmError as exc:
            lead.crm_attempts = (lead.crm_attempts or 0) + 1
            lead.crm_error = str(exc)[:255]
            log.warning("crm_push_failed", lead=str(lead_id), attempt=lead.crm_attempts,
                        error=str(exc)[:200])
            return {"synced": False, "reason": "rejected"}

        lead.crm_synced_at = datetime.now(UTC)
        lead.crm_error = None
        return {"synced": True}
