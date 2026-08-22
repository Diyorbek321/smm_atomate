"""FeedbackAgent — turns a voice/text correction into a structured instruction."""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.prompts import VOICE_INSTRUCTION_SYSTEM
from app.core.logging import get_logger
from app.models.content_item import ContentItem
from app.schemas.content import VoiceInstruction
from app.utils.dates import humanize

log = get_logger(__name__)

#: Keyword fallbacks when the model is unavailable.
_KEYWORDS = {
    "reject": ("bekor", "o'chir", "ochir", "kerakmas", "kerak emas"),
    "regenerate": ("qayta", "boshqatdan", "yangisini", "boshqa variant"),
    "reschedule": ("vaqtni", "ertaga", "kechqurun", "soat", "ko'chir", "kochir"),
    "change_price": ("narx", "so'm", "som", "ming", "chegirma"),
    "change_image": ("rasm", "surat", "foto", "rasmni"),
}


class FeedbackAgent(BaseAgent):
    name = "feedback"

    async def parse(
        self, message: str, item: ContentItem | None = None, tz_name: str | None = None
    ) -> VoiceInstruction:
        text = (message or "").strip()
        if not text:
            return VoiceInstruction(action="unknown", confidence=0.0)

        context = ""
        if item is not None:
            context = (
                f"POST KONTEKSTI:\n- Mavzu: {item.topic}\n- Format: {item.content_type}\n"
                f"- Rejalashtirilgan vaqt: {humanize(item.scheduled_at, tz_name)}\n"
                f"- Matn (qisqartirilgan): {item.caption_tg[:800]}"
            )

        prompt = "\n\n".join(filter(None, [context, f"EGANING XABARI:\n{text[:2000]}", "JSON qaytar."]))
        try:
            return await self.ask_json(
                prompt,
                VoiceInstruction,
                system=VOICE_INSTRUCTION_SYSTEM,
                temperature=0.15,
                max_tokens=700,
            )
        except Exception as exc:
            log.warning("feedback_parse_failed_keywords", error=str(exc)[:200])
            return self.keyword_fallback(text)

    @staticmethod
    def keyword_fallback(text: str) -> VoiceInstruction:
        lowered = text.lower()
        for action, needles in _KEYWORDS.items():
            if any(n in lowered for n in needles):
                return VoiceInstruction(
                    action=action,
                    instruction_for_writer=text[:500],
                    confidence=0.4,
                )
        return VoiceInstruction(action="edit_caption", instruction_for_writer=text[:500], confidence=0.3)
