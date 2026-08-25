"""HookAgent — writes the first line, and only the first line.

The copywriter already returns a ``hook`` field, but it writes it as part of a
whole post: the hook comes out serviceable and forgettable, because the model
spent its attention on the body. Asking a separate call for four competing
openings and picking one gets a materially stronger first line for the price of
a short prompt.

It runs after the copy is approved, so it rewrites the hook of a post that has
already passed the editor — never the other way round, or the editor would be
scoring a caption whose first line no longer exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent, knowledge_context
from app.agents.prompts import HOOK_SYSTEM
from app.core.logging import get_logger
from app.models.business import Business
from app.models.enums import ContentPillar, ContentType
from app.models.knowledge_base import KnowledgeBase

log = get_logger(__name__)

#: Longer than this and it stops being a hook — it is the first paragraph.
MAX_HOOK_CHARS = 90


class HookOptions(BaseModel):
    """Four competing openings plus the agent's own pick."""

    variants: list[str] = Field(default_factory=list, description="4 ta har xil hook")
    best_index: int = Field(default=0, ge=0, le=9)
    why: str = ""


@dataclass(slots=True)
class HookRequest:
    business: Business
    knowledge: KnowledgeBase | None
    content_type: ContentType
    pillar: ContentPillar
    topic: str
    caption: str
    current_hook: str = ""


@dataclass(slots=True)
class HookResult:
    hook: str
    variants: list[str]
    why: str = ""
    changed: bool = False


class HookAgent(BaseAgent):
    name = "hook"

    async def run(self, request: HookRequest) -> HookResult:
        system = await self.system_prompt(
            HOOK_SYSTEM, business_id=request.business.id, pillar=request.pillar
        )
        prompt = "\n\n".join(
            filter(
                None,
                [
                    knowledge_context(request.business, request.knowledge),
                    f"MAVZU: {request.topic}",
                    f"FORMAT: {request.content_type}",
                    f"POST MATNI:\n{(request.caption or '')[:1500]}",
                    f"HOZIRGI HOOK: {request.current_hook}" if request.current_hook else "",
                    "4 ta hook variantini yoz va eng kuchlisini tanla. JSON qaytar.",
                ],
            )
        )

        try:
            options = await self.ask_json(
                prompt, HookOptions, system=system, temperature=0.9, max_tokens=600
            )
        except Exception as exc:
            # A missing hook is not worth failing a post that is otherwise ready.
            log.warning("hook_failed_keep_original", error=str(exc)[:200])
            return HookResult(hook=request.current_hook, variants=[], changed=False)

        chosen = self._pick(options, request.current_hook)
        return HookResult(
            hook=chosen,
            variants=[v.strip() for v in options.variants if v.strip()],
            why=options.why.strip(),
            changed=bool(chosen and chosen != request.current_hook),
        )

    @staticmethod
    def _pick(options: HookOptions, fallback: str) -> str:
        """The model's pick when it is usable, else the first variant that is.

        ``best_index`` is frequently out of range on small models, and a hook
        that runs to three sentences is worse than the one already written — so
        both are treated as "the model did not answer" rather than trusted.
        """
        usable = [v.strip() for v in options.variants if v.strip() and len(v.strip()) <= MAX_HOOK_CHARS]
        if not usable:
            return fallback

        variants = [v.strip() for v in options.variants if v.strip()]
        if 0 <= options.best_index < len(variants):
            picked = variants[options.best_index]
            if len(picked) <= MAX_HOOK_CHARS:
                return picked
        return usable[0]
