"""VideoPromptAgent — writes a ready-to-run HyperFrames video prompt for a business.

The owner pastes the result into Claude Code (or any agent with the HyperFrames
skills) and gets an MP4. The prompt has two halves with different owners:

- the *creative* half — concept, scenes, sound, closing — is the model's call,
  grounded in the business profile, knowledge base and brand kit;
- the *technical* half — install line, `/hyperframes`, canvas size, the brand's
  accent colour, fonts, facts to stay inside, render to MP4 — is assembled here
  in code, so no draft can ever drop the part that makes the run succeed.

The model emits no geometry and no hex codes; the brand decides those.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent, knowledge_context
from app.agents.prompts import UZBEK_VOICE_RULES
from app.core.config import settings
from app.core.logging import get_logger
from app.models.business import Business
from app.models.knowledge_base import KnowledgeBase
from app.services.brand_kit import kit_for
from app.services.renderer import merge_colors

log = get_logger(__name__)

#: format key → (label used inside the prompt, what the model should build).
FORMATS: dict[str, tuple[str, str]] = {
    "showreel": (
        "dinamik motion-grafika shou-rili",
        "Brend imidji: biznesning kuchli tomonlarini harakat orqali ko'rsatadigan, "
        "so'zdan ko'ra motion ko'p ishlaydigan rolik.",
    ),
    "promo": (
        "promo motion-grafika",
        "Bitta aniq taklif yoki aksiyani sotadigan rolik: muammo → taklif → dalil → CTA.",
    ),
    "explainer": (
        "tushuntiruvchi motion-grafika",
        "Bitta mavzuni oddiy tilda tushuntiradigan rolik: savol → 2-3 qadam → xulosa.",
    ),
    "elon": (
        "e'lon motion-grafikasi",
        "Yangilik yoki tadbir e'loni: nima, qachon, qayerda, qanday yozilish.",
    ),
    "natija": (
        "natija va isbot motion-grafikasi",
        "Mijoz natijasi yoki raqam bilan ishonch uyg'otadigan rolik: oldin → keyin → qanday.",
    ),
}

#: aspect → canvas pixels.
ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "16:9": (1920, 1080),
}

MIN_SECONDS = 6
MAX_SECONDS = 60
MAX_SCENES = 8
MIN_SCENES = 2
SCENE_CHARS = 400
#: Below this a bare integer is structure ("3 qadam"), not a claim worth checking.
SMALL_NUMBER = 10

SYSTEM = f"""
Sen — AutoSMM AI ning MOTION-REJISSYOR agentisan. Sen video yaratmaysan —
sen boshqa AI agent (HyperFrames bilan ishlaydigan) uchun ROLIK G'OYASINI yozasan.

{UZBEK_VOICE_RULES}

QAROR QILADIGAN NARSALARING:
- concept: bitta gap — rolikning g'oyasi. Biznesga xos bo'lsin: shu g'oya boshqa
  biznesga ham tushsa, u yomon g'oya.
- message: tomoshabin eslab qoladigan BITTA fikr.
- scenes: 3-7 ta sahna. Har biri vaqt oralig'i bilan boshlansin ("0–2s: ...").
  Oraliqlar ketma-ket va umumiy davomiylikda tugasin. Har sahnada nima KO'RINADI
  va qanday HARAKAT qiladi — aniq yoz (masalan: "raqam 0 dan 600 ga sanaydi",
  "logotip bo'laklardan yig'iladi"). "Chiroyli animatsiya" kabi bo'sh gap yozma.
- sound: kod bilan sintez qilinadigan tovush effektlari — qaysi lahzada qanday
  tovush (zarb, whoosh, tick, akkord). Musiqa fayli yoki tayyor sample emas.
- closing: oxirgi kadr — brend nomi va bitta CTA.

TAQIQLAR:
- Rang kodlari, piksel o'lchamlari, shrift nomlari yozma — ular brenddan olinadi.
- Rang NOMLARINI ham yozma (qizil, yashil...). Faqat "urg'u rangi", "fon", "matn rangi"
  de — rolikda bitta urg'u rangi bo'ladi.
- Ekrandagi har bir raqam, narx, sana bilim bazasida AYNAN bo'lishi shart.
- Hamma maydonlarni o'zbekcha yoz, tovush tavsifini ham.
- Raqam, narx, natija — faqat bilim bazasidan. O'ylab topma.
- Raqobatchini tilga olma. Kafolat va'da qilma.
""".strip()


class VideoConcept(BaseModel):
    """The model's creative half. One list only — Gemini's schema budget."""

    title: str = Field(default="", max_length=80)
    concept: str = Field(default="", max_length=300)
    message: str = Field(default="", max_length=200)
    scenes: list[str] = Field(default_factory=list, max_length=12)
    sound: str = Field(default="", max_length=400)
    closing: str = Field(default="", max_length=200)


@dataclass(slots=True)
class VideoPromptRequest:
    business: Business
    knowledge: KnowledgeBase | None
    goal: str = ""
    format: str = "promo"
    duration: int = 15
    aspect: str = "9:16"
    extra: str = ""


@dataclass(slots=True)
class VideoPromptResult:
    prompt: str
    concept: VideoConcept
    fallback: bool
    #: Numbers the model put on screen that the knowledge base does not hold.
    unverified: list[str] = field(default_factory=list)


def clamp_duration(seconds: int) -> int:
    return max(MIN_SECONDS, min(int(seconds), MAX_SECONDS))


def _shorten(text: str, limit: int) -> str:
    """Cut on a word boundary — a scene ending mid-word reads as a bug."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{head}…"


def clean_scenes(scenes: list[str]) -> list[str]:
    cleaned = [_shorten(s.strip(), SCENE_CHARS) for s in scenes if s and s.strip()]
    return cleaned[:MAX_SCENES]


_TIME_RANGE = re.compile(r"\d+(?:[.,]\d+)?\s*[–-]\s*\d+(?:[.,]\d+)?\s*s\b")
_SECONDS = re.compile(r"\b\d+(?:[.,]\d+)?\s*s\b")
_NUMBER = re.compile(r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?")
_DIGIT_GAP = re.compile(r"(?<=\d)[ \u00a0](?=\d)")


def unknown_numbers(concept: VideoConcept, source: str) -> list[str]:
    """Numbers on screen that the source text does not contain.

    Timecodes ("0–3s", "12s") are direction, not claims, and are ignored, as
    are small bare integers. "600 000" and "600000" are the same number.
    """
    known = _DIGIT_GAP.sub("", source)
    text = " ".join([concept.title, concept.concept, concept.message, concept.closing, *concept.scenes])
    text = _SECONDS.sub(" ", _TIME_RANGE.sub(" ", text))
    found: list[str] = []
    for match in _NUMBER.findall(text):
        number = _DIGIT_GAP.sub("", match)
        if "." not in number and "," not in number and int(number) < SMALL_NUMBER:
            continue
        if number not in known and number not in found:
            found.append(number)
    return found


def _format(key: str) -> tuple[str, str]:
    return FORMATS.get(key, FORMATS["promo"])


def _contact(kb: KnowledgeBase | None) -> str:
    if kb is None:
        return ""
    parts = []
    if kb.telegram_username:
        parts.append(f"Telegram @{kb.telegram_username.lstrip('@')}")
    if kb.instagram_username:
        parts.append(f"Instagram @{kb.instagram_username.lstrip('@')}")
    if kb.phone:
        parts.append(kb.phone)
    if kb.website:
        parts.append(kb.website)
    return ", ".join(parts)


def _offerings(kb: KnowledgeBase | None) -> str:
    if kb is None:
        return ""
    names = [str(o.get("name", "")).strip() for o in (kb.key_offerings or []) if isinstance(o, dict)]
    return ", ".join(n for n in names if n)[:300]


def _absolute(url: str) -> str:
    """The video agent runs elsewhere — a path under our host means nothing to it."""
    if url.startswith(("http://", "https://")):
        return url
    return f"{settings.public_base_url.rstrip('/')}/{url.lstrip('/')}"


def _brand_lines(kb: KnowledgeBase | None) -> list[str]:
    """Facts the video agent may put on screen — and the words it may not."""
    kit = kit_for(kb.brand_kit if kb else None)
    lines = []
    if offerings := _offerings(kb):
        lines.append(f"- Xizmatlar: {offerings}")
    if kb and kb.usps:
        lines.append("- Kuchli tomonlar: " + "; ".join(str(u) for u in kb.usps[:4]))
    if contact := _contact(kb):
        lines.append(f"- Kontakt: {contact}")
    if kit.tagline:
        lines.append(f"- Shior: {kit.tagline}")
    if kit.voice.summary:
        lines.append(f"- Brend ovozi: {kit.voice.summary}")
    if kit.voice.banned_words:
        lines.append("- Ekranda ishlatilmaydigan so'zlar: " + ", ".join(kit.voice.banned_words))
    if kb and kb.logo_url:
        lines.append(f"- Logotip: {_absolute(kb.logo_url)}")
    return lines


def compose_prompt(
    request: VideoPromptRequest, concept: VideoConcept, unverified: list[str] | None = None
) -> str:
    """Assemble the final prompt. Pure — this is the part worth testing."""
    business = request.business
    kb = request.knowledge
    seconds = clamp_duration(request.duration)
    width, height = ASPECTS.get(request.aspect, ASPECTS["9:16"])
    label, _ = _format(request.format)
    colors = merge_colors(kb.brand_colors if kb else None)
    typography = kit_for(kb.brand_kit if kb else None).typography

    blocks = [
        "Avvalo, barcha kerakli vositalarni o'rnating: Node.js, FFmpeg va HyperFrames skills "
        "(npx hyperframes skills update). So'ngra /hyperframes yordamida "
        f"«{business.name}» uchun {seconds} soniyalik {label} videosini yarating.",
    ]

    idea = [f"G'oya: {concept.concept.strip()}" if concept.concept.strip() else "",
            f"Asosiy xabar: {concept.message.strip()}" if concept.message.strip() else ""]
    if any(idea):
        blocks.append("\n".join(line for line in idea if line))

    blocks.append(
        f"Parametrlar: {width}x{height} o'lcham, bitta urg'u rangi — {colors['accent']} "
        f"(fon {colors['bg']}, matn {colors['text']}), shriftlar: {typography.display} (sarlavha) "
        f"va {typography.body} (matn), kod orqali yaratilgan tovush effektlari. "
        "Ekrandagi matn o'zbek tilida (lotin)."
    )

    scenes = clean_scenes(concept.scenes)
    if scenes:
        blocks.append("Sahnalar:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(scenes, 1)))
    if concept.sound.strip():
        blocks.append(f"Tovush: {concept.sound.strip()}")
    if concept.closing.strip():
        blocks.append(f"Yakun: {concept.closing.strip()}")

    if brand := _brand_lines(kb):
        blocks.append("Brend ma'lumotlari (faqat shulardan foydalaning, raqam va faktni o'ylab topmang):\n"
                      + "\n".join(brand))
    if request.extra.strip():
        blocks.append(f"Qo'shimcha talab: {request.extra.strip()}")
    if unverified:
        blocks.append("Diqqat: bu raqamlar bilim bazasida tasdiqlanmagan — ekranga chiqarmang "
                      "yoki aniq qiymat bilan almashtiring: " + ", ".join(unverified))

    blocks.append("Videoni MP4 formatida render qiling. Bor mahoratingizni ishga soling.")
    return "\n\n".join(blocks)


def fallback_concept(request: VideoPromptRequest) -> VideoConcept:
    """A plain but correct concept from the profile, used when the model fails."""
    seconds = clamp_duration(request.duration)
    kb = request.knowledge
    name = request.business.name
    usp = str(kb.usps[0]) if kb and kb.usps else (_offerings(kb) or name)
    goal = request.goal.strip() or usp
    a, b = round(seconds * 0.25), round(seconds * 0.7)
    contact = _contact(kb)
    return VideoConcept(
        title=name,
        concept=f"«{name}» ning eng kuchli tomoni — {usp} — kinetik tipografiya bilan ochiladi.",
        message=goal,
        scenes=[
            f"0–{a}s: urg'u rangidagi shakl kadrga zarb bilan kiradi va «{goal}» yozuviga aylanadi",
            f"{a}–{b}s: {usp} — kalit so'zlar beat'ga mos ketma-ket chiqadi",
            f"{b}–{seconds}s: «{name}» lockup'i yig'iladi, ostida CTA",
        ],
        sound="Har kirishda qisqa zarb, o'tishlarda whoosh, lockup'da yorqin akkord.",
        closing=f"{name} — {contact}" if contact else name,
    )


class VideoPromptAgent(BaseAgent):
    name = "video_prompt"
    use_pro_model = True

    async def run(self, request: VideoPromptRequest) -> VideoPromptResult:
        concept = await self._concept(request)
        if concept is None:
            concept = fallback_concept(request)
            return VideoPromptResult(prompt=compose_prompt(request, concept), concept=concept, fallback=True)

        source = self._source(request)
        unverified = unknown_numbers(concept, source)
        if unverified:
            # One rewrite with the offending numbers named. If the model still
            # insists, the owner sees them flagged inside the prompt itself.
            note = ("TEKSHIRUV: bu raqamlar bilim bazasida yo'q: " + ", ".join(unverified)
                    + ". Ularni olib tashla yoki bilim bazasidagi raqam bilan almashtir.")
            retry = await self._concept(request, note=note)
            if retry is not None:
                concept, unverified = retry, unknown_numbers(retry, source)
        return VideoPromptResult(
            prompt=compose_prompt(request, concept, unverified),
            concept=concept,
            fallback=False,
            unverified=unverified,
        )

    @staticmethod
    def _source(request: VideoPromptRequest) -> str:
        """Everything the owner has told us — the only place a number may come from."""
        return "\n".join([
            knowledge_context(request.business, request.knowledge),
            "\n".join(_brand_lines(request.knowledge)),
            request.goal,
            request.extra,
        ])

    async def _concept(self, request: VideoPromptRequest, note: str = "") -> VideoConcept | None:
        label, brief = _format(request.format)
        seconds = clamp_duration(request.duration)
        system = await self.system_prompt(SYSTEM, business_id=request.business.id)
        prompt = "\n\n".join(
            filter(
                None,
                [
                    knowledge_context(request.business, request.knowledge),
                    "\n".join(_brand_lines(request.knowledge)),
                    f"FORMAT: {label}. {brief}",
                    f"DAVOMIYLIK: {seconds} soniya, {request.aspect}.",
                    f"MAQSAD: {request.goal.strip()}" if request.goal.strip() else "",
                    f"EGA QO'SHIMCHASI: {request.extra.strip()}" if request.extra.strip() else "",
                    note,
                    "Rolik g'oyasini JSON qaytar.",
                ],
            )
        )
        try:
            concept = await self.ask_json(prompt, VideoConcept, system=system, temperature=0.9, max_tokens=1400)
        except Exception as exc:
            log.warning("video_prompt_failed_using_fallback", error=str(exc)[:200])
            return None
        if len(clean_scenes(concept.scenes)) < MIN_SCENES or not concept.concept.strip():
            log.info("video_prompt_thin_concept", scenes=len(concept.scenes))
            return None
        return concept
