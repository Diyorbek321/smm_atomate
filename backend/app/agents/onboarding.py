"""OnboardingAgent — interviews the owner and maintains the knowledge base."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import ONBOARDING_SYSTEM
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models.business import Business
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_base import KnowledgeExtraction
from app.utils.json_tools import compact_json
from app.utils.text import normalize_apostrophes, normalize_hashtags

log = get_logger(__name__)

#: Ordered interview script — used when the LLM has no better follow-up.
INTERVIEW_QUESTIONS: list[tuple[str, str]] = [
    ("key_offerings", "Qanday kurs va xizmatlaringiz bor? Nomlari va davomiyligini ayting."),
    ("prices", "Narxlar qanday? Har bir kurs uchun oylik yoki to'liq narxni ayting."),
    ("usps", "Sizni raqobatchilardan nima ajratib turadi? 2-3 ta asosiy ustunlik."),
    ("social_proof", "O'quvchilaringizning eng yaxshi natijalari qanday? O'qituvchilar haqida ayting."),
    ("faq", "Mijozlar eng ko'p qanday savol beradi? 3-4 tasini javobi bilan ayting."),
    ("contact", "Aloqa uchun telefon raqami va Telegram username'ingizni yuboring."),
]


#: Gemini inline uploads top out at ~20MB per request and base64 inflates the
#: payload by a third, so cap the raw document well below that.
MAX_DOCUMENT_BYTES = 12 * 1024 * 1024

#: `+998 93 191 33 08`, `998931913308`, `93-191-33-08` — all phone shaped.
_PHONE_RE = re.compile(r"^[+()\d][\d\s\-()]{6,}$")


def looks_like_phone(value: str) -> bool:
    value = (value or "").strip()
    return bool(_PHONE_RE.match(value)) and sum(ch.isdigit() for ch in value) >= 7


def normalise_contacts(knowledge: KnowledgeBase) -> list[str]:
    """Put contact details in the right column whatever the model guessed.

    Models routinely drop a phone number into `telegram_username`; a caption
    would then render `✍️ @+998901234567`, so repair it here rather than hoping
    the prompt is obeyed.
    """
    fixed: list[str] = []

    for handle_field in ("telegram_username", "instagram_username"):
        value = (getattr(knowledge, handle_field) or "").strip()
        if not value:
            continue
        if looks_like_phone(value):
            if not knowledge.phone:
                knowledge.phone = value
                fixed.append("phone")
            setattr(knowledge, handle_field, None)
            fixed.append(handle_field)
        elif value.startswith("@"):
            setattr(knowledge, handle_field, value.lstrip("@"))
            fixed.append(handle_field)

    phone = (knowledge.phone or "").strip()
    if phone and not looks_like_phone(phone) and phone.startswith("@"):
        # The mirror image: a handle stored as the phone number.
        if not knowledge.telegram_username:
            knowledge.telegram_username = phone.lstrip("@")
            fixed.append("telegram_username")
        knowledge.phone = None
        fixed.append("phone")

    return fixed


@dataclass(slots=True)
class OnboardingResult:
    extraction: KnowledgeExtraction
    next_question: str | None
    completeness: float
    updated_fields: list[str]
    summary: str


class OnboardingAgent(BaseAgent):
    name = "onboarding"

    async def ingest(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        message: str,
        *,
        source: str = "telegram",
    ) -> OnboardingResult:
        """Extract structured facts from free-form owner input and merge them."""
        text = normalize_apostrophes((message or "").strip())
        if not text:
            return OnboardingResult(
                extraction=KnowledgeExtraction(),
                next_question=self.fallback_question(knowledge),
                completeness=knowledge.compute_completeness(),
                updated_fields=[],
                summary="Bo'sh xabar",
            )

        system = await self.system_prompt(ONBOARDING_SYSTEM, business_id=business.id)
        prompt = "\n\n".join(
            [
                f"BIZNES: {business.name} ({business.category}) — til: {business.language}",
                "MAVJUD BILIM BAZASI (JSON):\n" + knowledge.to_prompt_context(),
                "YETISHMAYOTGAN MAYDONLAR: " + compact_json(knowledge.missing_fields),
                f"EGA AYTGANLARI ({source}):\n{text[:6000]}",
                "Yuqoridagilardan faktlarni ajratib ol va JSON qaytar. "
                "Mavjud ma'lumotni yo'qotma, faqat to'ldir yoki yangila.",
            ]
        )

        extraction = await self.ask_json(
            prompt, KnowledgeExtraction, system=system, temperature=0.3, max_tokens=2500
        )
        updated = self.merge(knowledge, extraction, raw_message=text)
        return self._complete(business, knowledge, extraction, updated, source=source)

    async def ingest_document(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        data: bytes,
        *,
        mime_type: str = "application/pdf",
        filename: str = "document.pdf",
        source: str = "api",
    ) -> OnboardingResult:
        """Extract structured facts straight from an uploaded document (PDF).

        The document goes to the model as-is, so scanned/photographed PDFs work
        too — no local text extraction step to lose the layout or the images.
        """
        if not data:
            raise ValidationError("Hujjat bo'sh")
        if len(data) > MAX_DOCUMENT_BYTES:
            raise ValidationError("Hujjat juda katta — 12 MB dan oshmasin")

        system = await self.system_prompt(ONBOARDING_SYSTEM, business_id=business.id)
        prompt = "\n\n".join(
            [
                f"BIZNES: {business.name} ({business.category}) — til: {business.language}",
                "MAVJUD BILIM BAZASI (JSON):\n" + knowledge.to_prompt_context(),
                "YETISHMAYOTGAN MAYDONLAR: " + compact_json(knowledge.missing_fields),
                f"Ilova qilingan hujjat ({filename}) shu biznesga tegishli. "
                "Undagi barcha foydali faktlarni — kurslar/xizmatlar, narxlar, ustunliklar, "
                "o'qituvchilar, natijalar, FAQ, aloqa ma'lumotlari — ajratib ol va JSON qaytar. "
                "Mavjud ma'lumotni yo'qotma, faqat to'ldir yoki yangila.",
            ]
        )

        extraction = await self.ask_json(
            prompt,
            KnowledgeExtraction,
            system=system,
            temperature=0.3,
            max_tokens=2500,
            document=(mime_type, data),
        )
        note = f"[Hujjat: {filename}] {extraction.summary or ''}".strip()
        updated = self.merge(knowledge, extraction, raw_message=note)
        return self._complete(business, knowledge, extraction, updated, source=source)

    def _complete(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        extraction: KnowledgeExtraction,
        updated: list[str],
        *,
        source: str,
    ) -> OnboardingResult:
        """Shared tail of every ingest path: backfill, score, next question."""
        if extraction.target_audience and not business.target_audience:
            business.target_audience = extraction.target_audience[:2000]
            updated.append("target_audience")

        completeness = knowledge.compute_completeness()
        question = extraction.next_question or self.fallback_question(knowledge)
        if completeness >= 0.99:
            question = None

        log.info(
            "onboarding_ingested",
            business=str(business.id),
            source=source,
            updated=updated,
            completeness=completeness,
        )
        return OnboardingResult(
            extraction=extraction,
            next_question=question,
            completeness=completeness,
            updated_fields=updated,
            summary=extraction.summary or "Bilim bazasi yangilandi",
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def merge(knowledge: KnowledgeBase, extraction: KnowledgeExtraction, *, raw_message: str = "") -> list[str]:
        """Additive merge — never drops previously collected facts.

        List items are matched by their identity key (name / item / q / name)
        so a repeated price simply overwrites the old value.
        """
        updated: list[str] = []

        def merge_objects(current: list[dict[str, Any]], incoming: list[Any], key: str) -> list[dict[str, Any]]:
            index = {str(row.get(key, "")).strip().lower(): dict(row) for row in current if isinstance(row, dict)}
            for entry in incoming:
                data = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
                identity = str(data.get(key, "")).strip().lower()
                if not identity:
                    continue
                index[identity] = {**index.get(identity, {}), **{k: v for k, v in data.items() if v not in (None, "")}}
            return list(index.values())

        if extraction.key_offerings:
            knowledge.key_offerings = merge_objects(knowledge.key_offerings or [], extraction.key_offerings, "name")
            updated.append("key_offerings")
        if extraction.prices:
            knowledge.prices = merge_objects(knowledge.prices or [], extraction.prices, "item")
            updated.append("prices")
        if extraction.teacher_profiles:
            knowledge.teacher_profiles = merge_objects(
                knowledge.teacher_profiles or [], extraction.teacher_profiles, "name"
            )
            updated.append("teacher_profiles")
        if extraction.faq:
            knowledge.faq = merge_objects(knowledge.faq or [], extraction.faq, "q")
            updated.append("faq")
        if extraction.success_stories:
            knowledge.success_stories = merge_objects(
                knowledge.success_stories or [], extraction.success_stories, "name"
            )
            updated.append("success_stories")

        if extraction.usps:
            existing = {u.strip().lower() for u in (knowledge.usps or [])}
            merged = list(knowledge.usps or [])
            merged.extend(u for u in extraction.usps if u.strip() and u.strip().lower() not in existing)
            knowledge.usps = merged[:12]
            updated.append("usps")

        if extraction.preferred_hashtags:
            knowledge.preferred_hashtags = normalize_hashtags(
                list(knowledge.preferred_hashtags or []) + list(extraction.preferred_hashtags)
            )
            updated.append("preferred_hashtags")

        for field_name in ("phone", "telegram_username", "instagram_username", "address", "working_hours"):
            value = getattr(extraction, field_name, None)
            if value:
                setattr(knowledge, field_name, str(value)[:255])
                updated.append(field_name)

        updated.extend(normalise_contacts(knowledge))

        if raw_message:
            notes = (knowledge.raw_notes or "").strip()
            snippet = raw_message.strip()
            if snippet[:80] not in notes:
                knowledge.raw_notes = (notes + "\n\n" + snippet).strip()[-8000:]
                updated.append("raw_notes")

        knowledge.version = (knowledge.version or 0) + 1
        knowledge.compute_completeness()
        return sorted(set(updated))

    @staticmethod
    def fallback_question(knowledge: KnowledgeBase) -> str | None:
        """Next scripted question for whatever is still missing."""
        missing = set(knowledge.missing_fields)
        for field_name, question in INTERVIEW_QUESTIONS:
            if field_name in missing:
                return question
        return None

    @staticmethod
    def progress_text(knowledge: KnowledgeBase) -> str:
        percent = int(knowledge.completeness_score * 100)
        filled = "█" * (percent // 10)
        empty = "░" * (10 - percent // 10)
        return f"{filled}{empty} {percent}%"
