"""DesignerAgent — decides the composition; VisualAgent draws it.

The visual agent does two different jobs in one call: it decides what the card
should look like and it writes the Flux prompt that renders it. Composition is
a layout decision that depends on the copy — how long the headline is, whether
there is one number worth enlarging, whether a photo helps or just adds noise.
Splitting it out means the art direction can be reasoned about (and overridden
per business through the usual ``PromptTemplate`` route) without touching the
renderer.

The brief is advisory. VisualAgent keeps working unchanged when this agent is
disabled or fails — see ``settings.use_designer_agent``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.agents.prompts import DESIGNER_SYSTEM
from app.core.logging import get_logger
from app.models.business import Business
from app.models.enums import ContentPillar, ContentType
from app.models.knowledge_base import KnowledgeBase
from app.services.renderer import merge_colors

log = get_logger(__name__)

#: Layouts the renderer knows how to build. Anything else is treated as absent.
LAYOUTS = frozenset({"statement", "number", "split", "list", "quote", "photo"})
ACCENT_TARGETS = frozenset({"focal", "cta", "label", "none"})
DENSITIES = frozenset({"sparse", "packed"})

#: A headline longer than this does not fit a single-statement card.
STATEMENT_LIMIT = 60


class DesignBrief(BaseModel):
    """The composition decision handed to the visual agent."""

    layout: str = Field(default="statement")
    focal: str = Field(default="", description="Kadrdagi bitta diqqat markazi")
    accent_on: str = Field(default="focal")
    density: str = Field(default="sparse")
    photo_needed: bool = True
    reason: str = ""


@dataclass(slots=True)
class DesignRequest:
    business: Business
    knowledge: KnowledgeBase | None
    content_type: ContentType
    pillar: ContentPillar
    topic: str
    headline: str = ""
    hook: str = ""
    caption: str = ""
    cta: str = ""


class DesignerAgent(BaseAgent):
    name = "designer"

    async def run(self, request: DesignRequest) -> DesignBrief:
        # Polls carry no media at all, so there is nothing to compose.
        if request.content_type == ContentType.TELEGRAM_QUIZ:
            return DesignBrief(
                layout="statement",
                focal=request.headline[:60],
                accent_on="focal",
                density="sparse",
                photo_needed=False,
                reason="Quiz uchun rasm render qilinmaydi.",
            )

        system = await self.system_prompt(
            DESIGNER_SYSTEM, business_id=request.business.id, pillar=request.pillar
        )
        colors = merge_colors(request.knowledge.brand_colors if request.knowledge else None)
        prompt = "\n\n".join(
            filter(
                None,
                [
                    f"BREND: {request.business.name}",
                    f"URG'U RANGI: {colors['accent']}",
                    f"FORMAT: {request.content_type}  ·  USTUN: {request.pillar}",
                    f"MAVZU: {request.topic}",
                    f"SARLAVHA: {request.headline}",
                    f"HOOK: {request.hook}" if request.hook else "",
                    f"CTA: {request.cta}" if request.cta else "",
                    f"POST MATNI:\n{(request.caption or '')[:900]}",
                    "Kompozitsiya qarorini JSON qaytar.",
                ],
            )
        )

        try:
            brief = await self.ask_json(
                prompt, DesignBrief, system=system, temperature=0.4, max_tokens=500
            )
        except Exception as exc:
            log.warning("designer_failed_using_default", error=str(exc)[:200])
            return self._default(request)

        return self._sanitise(brief, request)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _default(request: DesignRequest) -> DesignBrief:
        """What the renderer did before this agent existed."""
        return DesignBrief(
            layout="statement",
            focal=request.headline[:60],
            accent_on="focal",
            density="sparse",
            photo_needed=True,
            reason="Dizayner javob bermadi — standart kompozitsiya.",
        )

    @staticmethod
    def _sanitise(brief: DesignBrief, request: DesignRequest) -> DesignBrief:
        """Force the brief back inside what the renderer can actually build.

        A free-text ``layout`` from a small model is regularly a word the
        renderer has never heard of; silently rendering nothing is worse than
        falling back to the layout that always works.
        """
        layout = brief.layout.strip().lower()
        if layout not in LAYOUTS:
            layout = "statement"

        focal = brief.focal.strip() or request.headline.strip()

        # The single-statement card overflows past this length — the model is
        # not good at judging it, so the length decides instead of the model.
        if layout == "statement" and len(focal) > STATEMENT_LIMIT:
            layout = "split"

        accent = brief.accent_on.strip().lower()
        if accent not in ACCENT_TARGETS:
            accent = "focal"

        density = brief.density.strip().lower()
        if density not in DENSITIES:
            density = "packed" if layout == "list" else "sparse"

        return DesignBrief(
            layout=layout,
            focal=focal[:120],
            accent_on=accent,
            density=density,
            photo_needed=bool(brief.photo_needed),
            reason=brief.reason.strip()[:200],
        )
