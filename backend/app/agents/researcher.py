"""ResearcherAgent — finds the checkable facts the copy is required to contain.

Every caption must carry something verifiable; :mod:`app.agents.facts` enforces
that by pulling numbers out of the knowledge base and demanding the copy use
them. That works only as long as the knowledge base has numbers in it. Nothing
put them there — the owner answered onboarding once and the well ran dry, so
the copywriter ends up recycling the same three prices.

This agent fills that well. It reads what the business already has (and any
document the owner uploads), extracts facts with their source, and says plainly
what is still missing so the bot can go and ask.

The two modules are deliberately split: this one *sources* facts, ``facts.py``
*serves* them. Neither invents any.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent, knowledge_context
from app.agents.prompts import RESEARCHER_SYSTEM
from app.core.logging import get_logger
from app.models.business import Business
from app.models.knowledge_base import KnowledgeBase

log = get_logger(__name__)

#: More than this and the owner is being handed a survey, not a question.
MAX_QUESTIONS = 5
#: Below this the model is guessing; the fact is kept but never auto-applied.
TRUSTED_CONFIDENCE = 0.6


class ResearchedFact(BaseModel):
    """One thing the copy could state, and where it came from."""

    label: str = Field(default="", description="Nima (masalan 'Backend kursi narxi')")
    value: str = Field(default="", description="Aniq qiymat (masalan '800000 so'm/oy')")
    source: str = Field(default="", description="ega aytdi | yuklangan hujjat | bilim bazasi")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @property
    def is_usable(self) -> bool:
        """A fact needs both halves and at least one digit to be checkable."""
        return bool(self.label.strip() and self.value.strip() and any(c.isdigit() for c in self.value))


class ResearchFindings(BaseModel):
    facts: list[ResearchedFact] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, description="Postlar uchun kerak, lekin topilmagan")
    questions: list[str] = Field(default_factory=list, description="Egadan so'raladigan savollar")

    def trusted(self) -> list[ResearchedFact]:
        return [f for f in self.facts if f.is_usable and f.confidence >= TRUSTED_CONFIDENCE]


@dataclass(slots=True)
class ResearchRequest:
    business: Business
    knowledge: KnowledgeBase | None
    #: Free-form text to mine — the owner's message, notes, a pasted price list.
    raw_text: str = ""
    #: ``(mime_type, data)`` for an uploaded PDF or image, as ``ask_json`` takes it.
    document: tuple[str, bytes] | None = None
    #: Facts already known, so the agent stops returning the same three prices.
    known_facts: list[str] = field(default_factory=list)


class ResearcherAgent(BaseAgent):
    name = "researcher"
    use_pro_model = True

    async def run(self, request: ResearchRequest) -> ResearchFindings:
        system = await self.system_prompt(RESEARCHER_SYSTEM, business_id=request.business.id)
        prompt = "\n\n".join(
            filter(
                None,
                [
                    knowledge_context(request.business, request.knowledge),
                    self._known_block(request.known_facts),
                    f"YANGI MATN:\n{request.raw_text[:6000]}" if request.raw_text.strip() else "",
                    (
                        "Yuklangan hujjat biriktirilgan — undagi faktlarni ham ol."
                        if request.document is not None
                        else ""
                    ),
                    "Faktlarni, yetishmayotgan joylarni va egaga savollarni JSON qaytar.",
                ],
            )
        )

        try:
            findings = await self.ask_json(
                prompt,
                ResearchFindings,
                system=system,
                temperature=0.2,
                max_tokens=1800,
                document=request.document,
            )
        except Exception as exc:
            log.warning("researcher_failed", business=str(request.business.id), error=str(exc)[:200])
            return ResearchFindings()

        return self._sanitise(findings, request.known_facts)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _known_block(known: list[str]) -> str:
        if not known:
            return ""
        listed = "\n".join(f"- {item}" for item in known[:40])
        return f"ALLAQACHON MA'LUM (bularni qayta qaytarma):\n{listed}"

    @staticmethod
    def _sanitise(findings: ResearchFindings, known: list[str]) -> ResearchFindings:
        """Drop facts that are unusable, duplicated, or already on file.

        The prompt asks for all three, and the model complies most of the time;
        the cases where it does not are exactly the ones that would put an
        invented price in front of a client.
        """
        seen: set[str] = {ResearcherAgent._key(item) for item in known}
        kept: list[ResearchedFact] = []
        for fact in findings.facts:
            if not fact.is_usable:
                continue
            key = ResearcherAgent._key(f"{fact.label} {fact.value}")
            if key in seen:
                continue
            seen.add(key)
            kept.append(fact)

        return ResearchFindings(
            facts=kept,
            gaps=[g.strip() for g in findings.gaps if g.strip()][:10],
            questions=[q.strip() for q in findings.questions if q.strip()][:MAX_QUESTIONS],
        )

    @staticmethod
    def _key(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())


#: Marks the block this module owns inside `raw_notes`, so a later run can tell
#: its own lines from whatever the owner typed there.
NOTES_HEADING = "TADQIQOT FAKTLARI:"


def merge_into_knowledge(knowledge: KnowledgeBase, findings: ResearchFindings) -> dict[str, Any]:
    """Append trusted facts to `raw_notes` without overwriting anything.

    Onboarding owns the structured fields (prices, courses, contacts) and this
    never touches them — a research run must not be able to silently change a
    price the owner set by hand. ``raw_notes`` is the one free-form field that
    already reaches every prompt through
    :meth:`KnowledgeBase.to_prompt_context`, so facts land there.

    That method truncates notes at 1500 characters, which caps how much this can
    usefully add; a dedicated column would lift the cap but needs a migration,
    so it is deliberately left for when the cap actually bites.
    """
    existing = knowledge.raw_notes or ""
    seen = {ResearcherAgent._key(line) for line in existing.splitlines() if line.strip()}

    added: list[str] = []
    for fact in findings.trusted():
        line = f"- {fact.label.strip()} — {fact.value.strip()}"
        if ResearcherAgent._key(line) in seen:
            continue
        seen.add(ResearcherAgent._key(line))
        added.append(line)

    if added:
        block = "\n".join(added)
        if NOTES_HEADING in existing:
            knowledge.raw_notes = f"{existing.rstrip()}\n{block}"
        else:
            joiner = "\n\n" if existing.strip() else ""
            knowledge.raw_notes = f"{existing.rstrip()}{joiner}{NOTES_HEADING}\n{block}"

    return {
        "added": len(added),
        "facts": added,
        "gaps": findings.gaps,
        "questions": findings.questions,
        "notes_chars": len(knowledge.raw_notes or ""),
    }
