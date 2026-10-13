"""Answers a stranger who wrote in from a post.

The tier sells `lead_autoreply` and until now only the Telegram bot honoured
it, with a scripted two-step flow: what are you interested in, what is your
phone number. That works in a bot, where the person has already chosen to press
Start. It does not work in an Instagram DM, where somebody asked a question and
being answered with a form is how a brand loses them.

So this answers the question — from the knowledge base, never from invention —
and asks for a number only after it has been useful. One message, because a
webhook has no session to hold a conversation in and pretending otherwise
produces a bot that repeats itself.

The guardrails are the ones a business owner would insist on if asked: never
invent a price, never promise an outcome, say plainly when the answer is not
in the knowledge base and hand the person to a human instead of guessing.
"""

from __future__ import annotations

from app.agents.base import BaseAgent, knowledge_context
from app.core.logging import get_logger
from app.models.business import Business
from app.models.knowledge_base import KnowledgeBase

log = get_logger(__name__)

#: Instagram truncates a long DM behind a "more" tap, and a wall of text from a
#: brand reads as automated before it reads as helpful.
MAX_CHARS = 480

SYSTEM = """Sen — biznesning {channel} sahifasiga yozgan odamga javob beruvchisan.

Sen sotuvchi emassan, yordamchisan. Odam savol berdi — avval SAVOLGA javob ber.

QOIDALAR:
- Til: o'zbekcha (lotin), jonli og'zaki. Rasmiy xat emas.
- 2-4 gap. Uzun yozma.
- Faktlar manbai: "SAYTDAGI RASMIY MA'LUMOT" (eng ishonchli), keyin bilim bazasi.
  Ikkalasi bir-biriga zid bo'lsa — saytdagisi to'g'ri.
- Narx, muddat, manzil, jadval, xizmat — FAQAT shu manbalardan, aynan o'sha kurs uchun.
  Bir kursning narxini boshqasiga BERMA.
- Manbada YO'Q narsani na tasdiqla, na inkor qil. "Bizda X yo'q" ham — o'ylab topish.
  Buning o'rniga: "Bu haqda aniq ma'lumotni operatorimiz beradi" de.
- Manbada "saytda yo'q" deb yozilgan bo'lsa — o'sha ma'lumotni aytma, operatorga yo'naltir.
- Daromad, natija yoki muddat VA'DA QILMA.
- Emoji ko'pi bilan bitta. Salomlashishga gap sarflama."""


class ReplyAgent(BaseAgent):
    name = "reply"

    async def answer(
        self,
        business: Business,
        knowledge: KnowledgeBase | None,
        question: str,
        *,
        public: bool = False,
        channel: str = "Instagram",
        ask_phone: bool = True,
    ) -> str:
        """One reply. Empty string when nothing safe can be said.

        Returning `""` rather than a filler apology is deliberate: the caller
        treats it as "leave this for a human", and a human reading it later is
        a better outcome than a brand account answering "I don't know" under
        its own post.
        """
        from app.services.crm import catalog_context_for

        try:
            catalog = await catalog_context_for(business)
        except Exception as exc:  # the knowledge base alone still answers
            log.warning("reply_catalog_failed", error=str(exc)[:200])
            catalog = ""
        prompt = "\n\n".join(filter(None, [
            knowledge_context(business, knowledge),
            catalog,
            f"ODAM YOZDI: {question.strip()[:600]}",
            ("Bu — post ostidagi OCHIQ komment. Hamma o'qiydi: qisqa (1-2 gap) "
             "va shaxsiy ma'lumotsiz javob ber."
             if public else
             "Bu — shaxsiy xabar (DM). Batafsilroq javob berishing mumkin."),
            ("Javob foydali bo'lgandan KEYIN, oxirida bir marta telefon raqam so'ra."
             if ask_phone and not public else
             "Telefon raqam SO'RAMA — bu suhbatda allaqachon so'ralgan."
             if not public else ""),
            f"Javob {MAX_CHARS} belgidan oshmasin.",
        ]))
        try:
            text = await self.ask_text(
                prompt,
                system=await self.system_prompt(
                    SYSTEM.format(channel=channel), business_id=business.id
                ),
                temperature=0.3,
                max_tokens=400,
            )
        except Exception as exc:
            log.warning("reply_failed", business=str(business.id), error=str(exc)[:200])
            return ""
        return (text or "").strip()[:MAX_CHARS]
