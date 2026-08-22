"""Common plumbing for every agent: model access, prompt overrides, telemetry."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RateLimitError
from app.core.logging import get_logger
from app.models.business import Business
from app.models.enums import ContentPillar
from app.models.knowledge_base import KnowledgeBase
from app.models.prompt_template import PromptTemplate
from app.services.llm import LLMResult, get_document_llm, get_llm

T = TypeVar("T", bound=BaseModel)

log = get_logger(__name__)


@dataclass(slots=True)
class AgentUsage:
    """Aggregated token/cost telemetry for one pipeline run."""

    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    models: list[str] = field(default_factory=list)

    def add(self, result: LLMResult) -> None:
        self.calls += 1
        self.prompt_tokens += result.prompt_tokens
        self.output_tokens += result.output_tokens
        self.cost_usd = round(self.cost_usd + result.cost_usd, 6)
        if result.model not in self.models:
            self.models.append(result.model)

    def merge(self, other: AgentUsage) -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.output_tokens += other.output_tokens
        self.cost_usd = round(self.cost_usd + other.cost_usd, 6)
        for model in other.models:
            if model not in self.models:
                self.models.append(model)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.prompt_tokens + self.output_tokens,
            "cost_usd": self.cost_usd,
            "models": self.models,
        }


class BaseAgent:
    """Base class handling prompt resolution and Gemini calls.

    Subclasses declare ``name`` (used to look up ``PromptTemplate`` overrides)
    and implement their own ``run`` method.
    """

    name: str = "agent"
    #: Prefer the pro model for reasoning-heavy agents.
    use_pro_model: bool = False

    def __init__(self, session: AsyncSession | None = None, usage: AgentUsage | None = None) -> None:
        self.session = session
        self.usage = usage or AgentUsage()
        self.llm = get_llm()

    # ------------------------------------------------------------------ #
    @property
    def model(self) -> str:
        return self.llm.model_pro if self.use_pro_model else self.llm.model_fast

    async def system_prompt(
        self,
        default: str,
        *,
        business_id: uuid.UUID | None = None,
        pillar: ContentPillar | None = None,
    ) -> str:
        """Return a DB override when present, otherwise the built-in prompt.

        Lookup order: (business, pillar) → (business, any) → (global, pillar) → default.
        """
        if self.session is None:
            return default

        stmt = (
            select(PromptTemplate)
            .where(PromptTemplate.agent == self.name, PromptTemplate.is_active.is_(True))
            .order_by(PromptTemplate.business_id.isnot(None).desc(), PromptTemplate.updated_at.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        if not rows:
            return default

        def _match(row: PromptTemplate, want_business: bool, want_pillar: bool) -> bool:
            business_ok = (row.business_id == business_id) if want_business else row.business_id is None
            pillar_ok = (row.pillar == pillar) if want_pillar else row.pillar is None
            return business_ok and pillar_ok

        for want_business, want_pillar in ((True, True), (True, False), (False, True), (False, False)):
            if want_business and business_id is None:
                continue
            if want_pillar and pillar is None:
                continue
            for row in rows:
                if _match(row, want_business, want_pillar):
                    row.usage_count += 1
                    log.debug("prompt_override_used", agent=self.name, template=row.name)
                    return row.system_prompt
        return default

    # ------------------------------------------------------------------ #
    async def ask_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        document: tuple[str, bytes] | None = None,
    ) -> T:
        """Structured call; pass ``document=(mime_type, data)`` to attach a file."""
        started = time.perf_counter()
        # Documents may route to a different provider than the active one, and
        # model names are provider-specific — so resolve both together.
        llm = get_document_llm() if document is not None else self.llm
        default_model = llm.model_pro if self.use_pro_model else llm.model_fast
        chosen = model if model and llm is self.llm else default_model

        async def call(with_model: str) -> tuple[T, LLMResult]:
            if document is not None:
                mime_type, data = document
                return await llm.generate_structured_document(
                    prompt,
                    schema,
                    data=data,
                    mime_type=mime_type,
                    system=system,
                    model=with_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            return await llm.generate_structured(
                prompt,
                schema,
                system=system,
                model=with_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        try:
            parsed, result = await call(chosen)
        except RateLimitError:
            # Free tiers usually exhaust the large model first; the small one
            # still produces a usable answer, which beats failing the run.
            if chosen == llm.model_fast:
                raise
            log.warning("llm_rate_limited_downgrade", agent=self.name, frm=chosen, to=llm.model_fast)
            parsed, result = await call(llm.model_fast)
        self.usage.add(result)
        log.info(
            "agent_call",
            agent=self.name,
            schema=schema.__name__,
            tokens=result.total_tokens,
            ms=int((time.perf_counter() - started) * 1000),
        )
        return parsed

    async def ask_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str:
        result = await self.llm.generate_text(
            prompt,
            system=system,
            model=model or self.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.usage.add(result)
        return result.text


def knowledge_context(business: Business, kb: KnowledgeBase | None) -> str:
    """Render the shared `BIZNES PROFILI + BILIM BAZASI` prompt block."""
    from app.agents.prompts import business_context_block

    return business_context_block(
        name=business.name,
        category=str(business.category),
        tone=str(business.tone_of_voice),
        audience=business.target_audience,
        language=str(business.language),
        knowledge_json=kb.to_prompt_context() if kb else "{}",
    )
