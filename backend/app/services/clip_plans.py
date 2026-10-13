"""A clip decided but not yet spoken — held between two messages.

Recording your own narration means reading the script first, and until now the
script only existed inside one `render_brief_clip` call: written, voiced and
rendered before anybody saw it. Owning the voice means owning that moment, so
the plan has to outlive the request that produced it.

One pending plan per business, deliberately. An owner works on one clip at a
time, and a queue of half-finished scripts waiting for voice messages is a
worse problem than losing the older of two — the newest ask is the one they
meant. A plan is a file rather than a table because it is short-lived, opaque
to every query the product makes, and worth nothing the moment it is rendered.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.storage import get_storage

log = get_logger(__name__)

#: A script the owner never recorded is not worth rendering days later — the
#: topic has moved on. Old enough plans are treated as absent.
MAX_AGE_SECONDS = 3 * 24 * 3600


@dataclass(slots=True)
class PendingPlan:
    business_id: str
    topic: str
    job: dict[str, Any]
    shape: dict[str, Any]
    created: float

    @property
    def says(self) -> list[str]:
        return [str(line) for line in (self.job.get("say") or [])]

    @property
    def stale(self) -> bool:
        return (time.time() - self.created) > MAX_AGE_SECONDS


def _root() -> Path:
    return Path(get_storage().root) / "plans"


def _path(business_id: uuid.UUID | str) -> Path:
    return _root() / f"{business_id}.json"


def save(business_id: uuid.UUID | str, topic: str,
         job: dict[str, Any], shape: dict[str, Any]) -> Path:
    path = _path(business_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"business_id": str(business_id), "topic": topic,
                    "job": job, "shape": shape, "created": time.time()},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("clip_plan_saved", business=str(business_id), lines=len(job.get("say") or []))
    return path


def load(business_id: uuid.UUID | str) -> PendingPlan | None:
    """The plan waiting on a voice message, or `None`.

    Unreadable and stale plans are both reported as absent: the caller's next
    move is the same either way, and a corrupt file should not take a bot
    handler down with it.
    """
    path = _path(business_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        log.warning("clip_plan_unreadable", business=str(business_id), error=str(exc)[:160])
        return None

    plan = PendingPlan(
        business_id=str(raw.get("business_id", business_id)),
        topic=str(raw.get("topic", "")),
        job=dict(raw.get("job") or {}),
        shape=dict(raw.get("shape") or {}),
        created=float(raw.get("created", 0.0)),
    )
    if plan.stale or not plan.says:
        log.info("clip_plan_expired", business=str(business_id))
        return None
    return plan


def clear(business_id: uuid.UUID | str) -> None:
    _path(business_id).unlink(missing_ok=True)
