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
- Faktlar manbai: bilim bazasi (egasi tasdiqlagan, eng ishonchli), keyin
  "SAYTDAGI MA'LUMOT". Ikkalasi bir-biriga zid bo'lsa — bilim bazasidagisi to'g'ri.
- Narx, muddat, manzil, jadval, xizmat — FAQAT shu manbalardan, aynan o'sha kurs uchun.
  Bir kursning narxini boshqasiga BERMA.
- Manbada YO'Q narsani na tasdiqla, na inkor qil. "Bizda X yo'q" ham — o'ylab topish.
  Buning o'rniga: "Bu haqda aniq ma'lumotni operatorimiz beradi" de.
- Saytda "saytda yo'q" deb yozilgan ma'lumot bilim bazasida ham bo'lmasa — aytma,
  operatorga yo'naltir.
- Daromad, natija yoki muddat VA'DA QILMA.
- Emoji ko'pi bilan bitta. Salomlashishga gap sarflama."""


def with_form_link(text: str, form_url: str) -> str:
    """The answer, ending with the enrolment form when the business has one.

    Appended here rather than asked of the model: a URL is the one thing a
    model must copy exactly, and it is the thing models most like to tidy up.
    An empty answer stays empty — that is the caller's "leave it for a human".
    """
    text = (text or "").strip()
    if not text or not form_url or form_url in text:
        return text
    suffix = f"\n\n📝 Ro'yxatdan o'tish: {form_url}"
    return text[: MAX_CHARS - len(suffix)].rstrip() + suffix


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
        from app.services.crm import catalog_context_for, crm_config

        cfg = crm_config(business)
        form_url = cfg.form_url if cfg and public else ""

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
             + (" Telefon raqam SO'RAMA va havola yozma — ro'yxatdan o'tish "
                "havolasi javob oxiriga avtomatik qo'shiladi." if form_url else "")
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
                # Headroom for the fallback's reasoning tokens; MAX_CHARS caps the reply.
                max_tokens=1500,
            )
        except Exception as exc:
            log.warning("reply_failed", business=str(business.id), error=str(exc)[:200])
            return ""
        return with_form_link((text or "").strip()[:MAX_CHARS], form_url)
