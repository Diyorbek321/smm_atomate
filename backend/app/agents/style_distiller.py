"""StyleDistillerAgent — turns this business's own feedback into standing rules.

The pipeline has always collected two streams of feedback and acted on
neither. The owner writes a reason when rejecting a post, and the reason dies
with the post; the editor flags the same problem week after week, and every
week the copywriter makes it again. This agent reads both streams, distils
them into a handful of concrete rules, and stores the result as a ``learned:``
prompt addendum — which :func:`app.agents.base.resolve_prompt` appends to the
copywriter's system prompt from then on.

Learned rules persist until a fresh distillation replaces them (or the owner
edits the template in Prompt Studio). Feedback ageing out of the window does
not erase a rule: "never post prices on Fridays" stays true after the message
that taught it is gone.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import LEARNED_PREFIX, BaseAgent
from app.agents.prompts import MAX_LEARNED_RULES, STYLE_DISTILLER_SYSTEM
from app.core.config import settings
from app.core.logging import get_logger
from app.models.business import Business
from app.models.content_item import SUPERSEDED_NOTE, ContentItem
from app.models.enums import ContentItemStatus
from app.models.prompt_template import PromptTemplate
from app.utils.json_tools import compact_json

log = get_logger(__name__)

MAX_RULE_CHARS = 200
#: An editor issue seen once is an accident; a rule needs a pattern.
MIN_ISSUE_REPEATS = 2
#: How many rejections / distinct repeated issues are worth prompting with.
MAX_REJECTIONS_SHOWN = 12
MAX_ISSUES_SHOWN = 10

#: The addendum row this agent owns, one per business.
TEMPLATE_NAME = LEARNED_PREFIX + "copywriter"


class DistilledRules(BaseModel):
    rules: list[str] = Field(default_factory=list)
    summary: str = ""


@dataclass(slots=True)
class DistillRequest:
    business: Business
    #: :func:`feedback_digest` output.
    digest: dict[str, Any] = field(default_factory=dict)


def feedback_digest(items: list[ContentItem]) -> dict[str, Any]:
    """Both feedback streams, aggregated small enough to prompt with.

    A pure function over rows already loaded, like ``production_stats`` — the
    part worth unit-testing, kept free of database access. Superseded rows are
    skipped: a plan regeneration rejects its drafts without anyone disliking
    them, and reading those as owner feedback would teach phantom lessons.
    """
    rejections: list[dict[str, str]] = []
    issue_counts: Counter[str] = Counter()
    for item in items:
        note = (item.review_notes or "").strip()
        if item.status == ContentItemStatus.REJECTED and note and note != SUPERSEDED_NOTE:
            rejections.append({"mavzu": (item.topic or "")[:80], "izoh": note[:200]})
        for issue in (item.editor_report or {}).get("issues", []):
            if isinstance(issue, dict) and issue.get("severity") in ("critical", "major"):
                problem = str(issue.get("problem", "")).strip()[:100]
                if problem:
                    issue_counts[problem] += 1

    repeated = {
        problem: count
        for problem, count in issue_counts.most_common(MAX_ISSUES_SHOWN)
        if count >= MIN_ISSUE_REPEATS
    }
    return {
        "rejections": rejections[:MAX_REJECTIONS_SHOWN],
        "repeated_issues": repeated,
        # An owner's written reason outweighs a linter hit, but for the "is
        # there anything to learn from" floor they count the same way.
        "signals": len(rejections) + sum(repeated.values()),
    }


def render_rules_block(rules: list[str]) -> str:
    """The addendum exactly as the copywriter will read it."""
    if not rules:
        return ""
    listed = "\n".join(f"- {rule}" for rule in rules)
    return (
        "SHU BIZNESDA O'RGANILGAN QOIDALAR (ega fikri va muharrir "
        f"topilmalaridan, majburiy):\n{listed}"
    )


class StyleDistillerAgent(BaseAgent):
    name = "style_distiller"
    use_pro_model = True

    async def run(self, request: DistillRequest) -> DistilledRules:
        digest = request.digest
        if int(digest.get("signals") or 0) < settings.style_min_signals:
            return DistilledRules()

        system = await self.system_prompt(STYLE_DISTILLER_SYSTEM, business_id=request.business.id)
        prompt = "\n\n".join(
            [
                f"BIZNES: {request.business.name}",
                f"EGA RAD ETGANLARI:\n{compact_json(digest.get('rejections') or [])}",
                "MUHARRIR TAKROR TOPGANLARI (muammo: nechta postda):\n"
                + compact_json(digest.get("repeated_issues") or {}),
                "Kopirayter uchun qoidalarni JSON qaytar: rules, summary.",
            ]
        )
        try:
            raw = await self.ask_json(
                prompt, DistilledRules, system=system, temperature=0.3, max_tokens=900
            )
        except Exception as exc:
            log.warning(
                "style_distiller_failed", business=str(request.business.id), error=str(exc)[:200]
            )
            return DistilledRules()
        return self._clamp(raw)

    @staticmethod
    def _clamp(raw: DistilledRules) -> DistilledRules:
        """Deterministic hygiene: dedupe, trim, cap — the model is not trusted."""
        seen: set[str] = set()
        rules: list[str] = []
        for rule in raw.rules:
            trimmed = " ".join(str(rule).split()).strip(" -•")
            key = trimmed.lower()
            if not trimmed or len(trimmed) > MAX_RULE_CHARS or key in seen:
                continue
            seen.add(key)
            rules.append(trimmed)
            if len(rules) >= MAX_LEARNED_RULES:
                break
        return DistilledRules(rules=rules, summary=" ".join(raw.summary.split())[:300])


async def save_rules(
    session: AsyncSession, business_id: uuid.UUID, rules: list[str]
) -> bool:
    """Upsert the business's learned addendum; True when anything changed.

    Empty rules are a no-op, never a deletion: the distiller declining to
    learn this week must not erase what it learned last month.
    """
    block = render_rules_block(rules)
    if not block:
        return False

    row = (
        await session.execute(
            select(PromptTemplate).where(
                PromptTemplate.business_id == business_id,
                PromptTemplate.name == TEMPLATE_NAME,
            )
        )
    ).scalars().one_or_none()

    if row is None:
        session.add(
            PromptTemplate(
                business_id=business_id,
                name=TEMPLATE_NAME,
                agent="copywriter",
                system_prompt=block,
            )
        )
        await session.flush()
        return True

    if row.system_prompt.strip() == block.strip() and row.is_active:
        return False

    row.push_version()
    row.system_prompt = block
    row.is_active = True
    await session.flush()
    return True
