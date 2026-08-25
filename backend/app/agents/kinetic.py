"""KineticAgent — writes a scene script and renders an agency-style promo.

Two lengths share one engine. The short mode is the reference genre: one
phrase per scene, 12-18 seconds, made for feeds and stories. The long mode
adds numbered chapters and figure scenes so a minute holds together, and
leaves room for a voice-over the owner records afterwards.

The LLM only writes the script; the visuals are deterministic
(:mod:`app.services.kinetic`), so a clip is always on-brand and free to render.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent, knowledge_context
from app.core.logging import get_logger
from app.models.business import Business
from app.models.enums import BusinessCategory
from app.models.knowledge_base import KnowledgeBase
from app.services.brand_assets import photo_library, prop_library
from app.services.brand_kit import kit_for
from app.services.kinetic import (
    KineticResult,
    KineticSpec,
    Scene,
    reading_time,
    render_kinetic,
)
from app.services.storage import get_storage
from app.utils.text import truncate_caption

log = get_logger(__name__)

SCENE_KINDS = ("text", "prop", "stat", "chapter", "split", "code")

#: Structured output sometimes fills an unused field with the word "null"
#: instead of leaving it empty — printed on a card it reads as a bug.
EMPTY_MARKERS = {"null", "none", "undefined", "n/a", "-", "—"}


def clean_field(text: str) -> str:
    return "" if text.strip().lower() in EMPTY_MARKERS else text.strip()

KINETIC_SYSTEM = """
Sen — kinetik tipografiya (motion design) ssenariystisan. Vertikal reklama klipi
uchun sahnalar yozasan.

SAHNA TURLARI:
- kind="text"    — bitta qisqa ibora (maksimal 6 so'z).
- kind="prop"    — matn + rasm ko'rsatiladi. Matn juda qisqa (max 4 so'z).
- kind="stat"    — bitta RAQAM sahnasi: `value` da raqam ("350 000",
                   "10 yil", "5 yo'nalish"), `text` da uning izohi (max 4 so'z).
- kind="chapter" — bo'lim ajratkichi: `value` da tartib raqami ("01"),
                   `text` da bo'lim nomi (1-3 so'z, masalan "TIL KURSLARI").
- kind="split"   — ikki tomonni YONMA-YON taqqoslash: `text` chap ustun nomi,
                   `value` o'ng ustun nomi, `items` da AYNAN 2 ta qator —
                   birinchisi chap ustun izohi, ikkinchisi o'ng ustun izohi
                   (har biri max 6 so'z). "X vs Y" mavzulari uchun eng kuchli.
- kind="code"    — terminal oynasida kod yoziladi: `items` da 2-4 qator kod
                   (haqiqiy, sodda, max 34 belgi), `text` da qisqa sarlavha.
                   IT mavzularida ishlating.

UMUMIY QOIDALAR (qat'iy):
- Har iborada bitta ACCENT so'z bo'lsin — `accent` maydonida o'sha so'zni
  qaytar (iboradagi so'z bilan bir xil yozilsin).
- Faktlarni faqat bilim bazasidan ol. Narx yoki natija TO'QIMA.
- `sub` — kamdan-kam, faqat qo'shimcha izoh kerak bo'lganda (max 7 so'z).
- Til jonli va zarbdor: "Reklama bermang. E'tibor QOZONING." uslubida.
- Bir xil so'zni sahnama-sahna takrorlama.
""".strip()

SHORT_BRIEF = """
UZUNLIK: 12-18 soniya, 5-7 sahna.
TUZILISH: 1-sahna og'riq/savol (hook) → o'rtada va'da va dalil →
oxirgi sahna harakatga chaqiriq. Bitta sahna kind="prop" bo'lsin.
duration: 1.6-2.6 (hook 2.2+, qolganlari ~1.9).
""".strip()

LONG_BRIEF = """
UZUNLIK: 55-65 soniya, 22-26 sahna. Bu — markazning tanitish klipi.
TUZILISH (qat'iy shu tartibda):
1) HOOK — 2 ta kind="text" sahna: muammo yoki kuchli savol.
2) 4 ta BO'LIM. Har bo'lim: 1 ta kind="chapter" (value="01".."04") +
   uning ichida 2-3 sahna (kind="text", "stat" yoki "prop" aralash).
   Bo'limlar bilim bazasidagi yo'nalishlar va ustunliklardan olinsin.
3) ISBOT — 1-2 sahna: kind="stat" (tajriba yili, o'quvchilar soni, natija).
4) YAKUN — 2 ta kind="text": harakatga chaqiriq.
duration: chapter 1.8, stat 2.4, prop 2.6, text 2.2-2.6.
MUHIM: bu klip ustiga keyin ovoz yoziladi — matnlar ovoz bilan takrorlanadigan
uzun jumlalar emas, qisqa va zarbdor sarlavhalar bo'lsin.
""".strip()

#: Kinetic typography is the worst case for compression: hard type edges on
#: flat fields, where a high CRF shows as mosquito noise around every letter.
#: These sit well below the old 22/24 because the platform will re-encode on
#: top of ours. The bitrate ceiling is what keeps a long clip inside the
#: Telegram bot limit — 5 Mbit/s caps a minute at roughly 37 MB.
CRF_BY_LENGTH = {"short": 19, "long": 21}
RATE_BY_LENGTH = {"short": ("12M", "24M"), "long": ("5M", "10M")}


class KineticSceneSpec(BaseModel):
    kind: str = Field(default="text", description="text | prop | stat | chapter | split | code")
    text: str = ""
    accent: str = ""
    sub: str = ""
    value: str = ""
    items: list[str] = Field(default_factory=list)
    duration: float = 2.0


class KineticScript(BaseModel):
    scenes: list[KineticSceneSpec] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ClipFrame:
    """The scaffolding of a fallback clip for one kind of business.

    Deliberately holds no claims and no figures. Everything here has to be
    true of *every* business in the category, and the only sentences that
    clear that bar are questions, section labels and invitations. Anything
    stronger — an experience figure, a promise about class sizes — either
    comes out of the knowledge base or does not go on screen at all.
    """

    #: Section labels for the long cut.
    chapters: tuple[str, str, str]
    #: Said in place of a USP when the knowledge base has none. A question, so
    #: it cannot be false for the business it is standing in for.
    claim: str
    #: A second one, for the same reason. Two are needed because a clip with a
    #: single scaffolding line either repeats it or runs short.
    invitation: str
    #: What this kind of business sells — labels an offering on screen.
    offering_word: str
    #: The closing line. A functional CTA, which the empty-phrase rule allows.
    closing: str


GENERIC_FRAME = ClipFrame(
    chapters=("Biz haqimizda", "Nima taklif qilamiz", "Bog'lanish"),
    claim="Sizga nima kerak?",
    invitation="Bir ko'rib chiqing",
        offering_word="xizmat",
    closing="Bugun bog'laning",
)

CLIP_FRAMES: dict[BusinessCategory, ClipFrame] = {
    BusinessCategory.EDUCATION: ClipFrame(
        chapters=("Yo'nalishlar", "Ustozlar", "Natija"),
        claim="Qaysi yo'nalish sizga mos?",
        invitation="Darsga kelib ko'ring",
        offering_word="kurs",
        closing="Bugun boshlang",
    ),
    BusinessCategory.FOOD_BEVERAGE: ClipFrame(
        chapters=("Menyu", "Oshxona", "Buyurtma"),
        claim="Bugun nima yeymiz?",
        invitation="Kelib tatib ko'ring",
        offering_word="taom",
        closing="Buyurtma bering",
    ),
    BusinessCategory.RETAIL: ClipFrame(
        chapters=("Assortiment", "Do'kon", "Yetkazish"),
        claim="Nimani qidiryapsiz?",
        invitation="Yangi kelganlar bor",
        offering_word="mahsulot",
        closing="Do'konga keling",
    ),
    BusinessCategory.BEAUTY: ClipFrame(
        chapters=("Xizmatlar", "Ustalar", "Natija"),
        claim="Yangi ko'rinish vaqtimi?",
        invitation="Bir kelib ko'ring",
        offering_word="xizmat",
        closing="Navbat oling",
    ),
    BusinessCategory.HEALTHCARE: ClipFrame(
        chapters=("Yo'nalishlar", "Shifokorlar", "Qabul"),
        claim="Qaysi savolingiz bor?",
        invitation="Savolingizni bering",
        offering_word="xizmat",
        closing="Qabulga yoziling",
    ),
    BusinessCategory.REAL_ESTATE: ClipFrame(
        chapters=("Obyektlar", "Joylashuv", "Shartlar"),
        claim="Qanday uy qidiryapsiz?",
        invitation="Ko'rikka kelib ko'ring",
        offering_word="obyekt",
        closing="Ko'rikka yoziling",
    ),
    BusinessCategory.TECH: ClipFrame(
        chapters=("Yechimlar", "Jamoa", "Ish jarayoni"),
        claim="Qanday masalani yechamiz?",
        invitation="Keling, gaplashamiz",
        offering_word="xizmat",
        closing="Loyihani muhokama qilamiz",
    ),
}
#: Same shelf, same clip — as in the shooting brief's catalogue.
CLIP_FRAMES[BusinessCategory.ECOMMERCE] = CLIP_FRAMES[BusinessCategory.RETAIL]


def frame_for(category: BusinessCategory | str) -> ClipFrame:
    """This category's frame, or the generic one for anything unmapped."""
    try:
        return CLIP_FRAMES.get(BusinessCategory(category), GENERIC_FRAME)
    except ValueError:
        return GENERIC_FRAME


def _known_lines(knowledge: KnowledgeBase | None, limit: int = 3) -> list[str]:
    """Short, true things this business has actually told us."""
    if knowledge is None:
        return []
    lines: list[str] = []
    for usp in (knowledge.usps or []):
        text = str(usp).strip()
        if text and len(text) <= FALLBACK_LINE_MAX:
            lines.append(text)
        if len(lines) >= limit:
            break
    return lines


def _known_stats(knowledge: KnowledgeBase | None, limit: int = 2) -> list[Scene]:
    """Figures the owner supplied, as stat cards. Never anything we made up."""
    if knowledge is None:
        return []

    from app.agents.facts import collect_facts

    stats: list[Scene] = []
    for fact in collect_facts(knowledge, limit=6):
        if not fact.is_priced or len(fact.label) > FALLBACK_LINE_MAX:
            continue
        stats.append(Scene(kind="stat", value=fact.value[:18], text=fact.label, duration=2.4))
        if len(stats) >= limit:
            break
    return stats


#: Longer than this and the line does not fit the card it is drawn on.
FALLBACK_LINE_MAX = 34


def fallback_script(
    topic: str, business: Business, knowledge: KnowledgeBase | None, length: str
) -> list[Scene]:
    """A clip without the model — built from this business, not from a template.

    The scaffolding is per category so a bakery does not sign off with a
    language centre's chapter headings, and the *content* comes from the
    knowledge base so the clip says something only this business could say.
    When the knowledge base is empty the clip gets shorter and plainer rather
    than padded with claims nobody can stand behind.
    """
    frame = frame_for(business.category)
    head = (topic or business.name or "Yangiliklarimiz bor").strip()

    offerings = [
        str(entry.get("name", "")).strip()
        for entry in (knowledge.key_offerings if knowledge else []) or []
        if str(entry.get("name", "")).strip()
    ]

    # One pool, drawn from in order and never twice. Repetition is the failure
    # this shape exists to prevent: a thin knowledge base used to leave the
    # same question on screen twice in one clip, which reads as a broken render
    # rather than a short one.
    #
    # The frame's two scaffolding lines are the floor, not filler — once even
    # those are spent the clip says less instead of saying something again. The
    # business name is deliberately absent: it is already the prop card's
    # caption and the outro's headline.
    pool: list[str] = []
    seen: set[str] = set()
    for candidate in [*offerings, *_known_lines(knowledge), frame.claim, frame.invitation]:
        text = candidate.strip()
        key = text.lower()
        if text and key not in seen and len(text) <= FALLBACK_LINE_MAX:
            seen.add(key)
            pool.append(text)

    used = 0

    def take() -> str:
        """The next unused line, or empty once the pool is spent."""
        nonlocal used
        if used < len(pool):
            used += 1
            return pool[used - 1]
        return ""

    def say(text: str, duration: float, sub: str = "") -> Scene:
        return Scene(
            kind="text", text=text, accent=text.split()[-1], sub=sub, duration=duration
        )

    opening = Scene(kind="text", text=head, accent=head.split()[-1], duration=2.3)
    # A bare product name needs the noun: "Somsa" alone is a word on a card,
    # "Somsa / taom" tells a viewer who arrived mid-scroll what it is.
    first = take()
    offering_sub = frame.offering_word if offerings and first == offerings[0] else ""

    def maybe_say(duration: float) -> list[Scene]:
        """A spoken scene when the pool still has one, nothing when it does not."""
        text = take()
        return [say(text, duration)] if text else []

    if length != "long":
        return [
            opening,
            say(first, 2.1, offering_sub),
            *maybe_say(1.9),
            Scene(kind="prop", text=frame.closing, accent=frame.closing.split()[0],
                  sub=business.name, duration=2.2),
        ]

    scenes = [
        opening,
        Scene(kind="chapter", value="01", text=frame.chapters[0], duration=1.8),
        say(first, 2.3, offering_sub),
        # The prop card carries a rendered object, so it is captioned with the
        # brand rather than a chapter name it would otherwise duplicate.
        Scene(kind="prop", text=business.name, accent=business.name.split()[0], duration=2.5),
        Scene(kind="chapter", value="02", text=frame.chapters[1], duration=1.8),
        *maybe_say(2.4),
        Scene(kind="chapter", value="03", text=frame.chapters[2], duration=1.8),
    ]
    # Supplied figures go in before the close; an empty knowledge base simply
    # yields none, and the clip is that much shorter.
    scenes.extend(_known_stats(knowledge))
    scenes.extend(maybe_say(2.4))
    scenes.append(
        Scene(kind="text", text=frame.closing, accent=frame.closing.split()[0], duration=2.2)
    )
    return scenes


#: The outro line is drawn centred at font 32 on a fixed-width card, so it
#: cannot wrap or shrink. Longer than this and it runs off both edges.
TAGLINE_MAX = 42


def outro_tagline(knowledge: KnowledgeBase | None) -> str:
    """The line under the business name on the closing card.

    This was one client's corporate positioning, written straight into the
    shared outro, so every other business signed its clip off with a language
    centre's slogan. It comes from the brand now.

    An empty answer is a real answer: the card already carries the name, the
    logo and the phone number, and somebody else's slogan under a bakery's name
    is worse than no slogan at all.
    """
    if knowledge is None:
        return ""

    kit = kit_for(getattr(knowledge, "brand_kit", None))
    tagline = kit.tagline.strip()
    if tagline:
        # Dropped rather than cut: a slogan sliced mid-word reads as a bug.
        return tagline if len(tagline) <= TAGLINE_MAX else ""

    # No tagline set — a USP is the closest thing the knowledge base holds.
    for usp in (knowledge.usps or []):
        text = str(usp).strip()
        if text and len(text) <= TAGLINE_MAX:
            return text
    return ""


def build_outro(business: Business, knowledge: KnowledgeBase | None) -> Scene:
    """The closing card: the name, and whatever the brand says under it."""
    return Scene(
        kind="outro", text=business.name, sub=outro_tagline(knowledge), duration=2.6
    )


class KineticAgent(BaseAgent):
    name = "kinetic"

    async def run(
        self,
        business: Business,
        knowledge: KnowledgeBase | None,
        topic: str,
        *,
        length: str = "short",
    ) -> KineticResult:
        length = "long" if str(length).lower() == "long" else "short"
        system = await self.system_prompt(KINETIC_SYSTEM, business_id=business.id)
        prompt = "\n\n".join(
            [
                knowledge_context(business, knowledge),
                LONG_BRIEF if length == "long" else SHORT_BRIEF,
                f"KLIP MAVZUSI: {topic}",
                "Sahnalar ro'yxatini JSON qaytar.",
            ]
        )
        limit = 28 if length == "long" else 7
        try:
            script = await self.ask_json(
                prompt,
                KineticScript,
                system=system,
                temperature=0.9,
                max_tokens=3000 if length == "long" else 1200,
            )
            scenes = [self._to_scene(spec) for spec in script.scenes[:limit] if self._usable(spec)]
        except Exception as exc:
            log.warning("kinetic_script_failed_fallback", error=str(exc)[:200])
            scenes = []

        minimum = 8 if length == "long" else 3
        if len(scenes) < minimum:
            log.info("kinetic_script_too_short", got=len(scenes), length=length)
            scenes = fallback_script(topic, business, knowledge, length)

        # The outro card is deterministic — never trusted to the model.
        scenes.append(build_outro(business, knowledge))

        # The model writes for rhythm, not for reading speed — give every scene
        # (the outro included) at least the time a viewer needs to finish it.
        for scene in scenes:
            scene.duration = max(scene.duration, reading_time(scene))

        if length == "long":
            self._fit_duration(scenes, target=58.0)

        spec = KineticSpec(
            scenes=scenes,
            colors=dict(knowledge.brand_colors) if knowledge and knowledge.brand_colors else {},
            brand=business.name,
            phone=(knowledge.phone if knowledge else "") or "",
            footer=(knowledge.address if knowledge else "") or "",
            logo=self._logo_bytes(knowledge),
            prop_photos=photo_library(business.id, topic),
            prop_renders=prop_library(business.id, topic),
            music=self._music(),
        )
        total = sum(scene.duration for scene in scenes)
        log.info("kinetic_script_ready", length=length, scenes=len(scenes), seconds=round(total, 1))
        maxrate, bufsize = RATE_BY_LENGTH[length]
        return await render_kinetic(
            spec, crf=CRF_BY_LENGTH[length], maxrate=maxrate, bufsize=bufsize
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _usable(spec: KineticSceneSpec) -> bool:
        if spec.kind == "split":
            return bool(spec.text.strip() and spec.value.strip())
        if spec.kind == "code":
            return bool([item for item in spec.items if item.strip()])
        if spec.kind == "stat":
            return bool(spec.value.strip())
        if spec.kind == "chapter":
            return bool(spec.text.strip() or spec.value.strip())
        return bool(spec.text.strip())

    @staticmethod
    def _to_scene(spec: KineticSceneSpec) -> Scene:
        kind = spec.kind if spec.kind in SCENE_KINDS else "text"
        text, value = clean_field(spec.text), clean_field(spec.value)
        # A figure with no label reads as a riddle ("11" — of what?). Without a
        # caption the number is better told as an ordinary phrase.
        if kind == "stat" and not text:
            kind, text, value = "text", value, ""
        return Scene(
            kind=kind,
            text=truncate_caption(text, 60),
            accent=clean_field(spec.accent),
            sub=truncate_caption(clean_field(spec.sub), 60),
            value=truncate_caption(value, 24),
            items=[
                truncate_caption(clean_field(item), 70)
                for item in spec.items[:5]
                if clean_field(item)
            ],
            duration=min(6.5, max(1.6, spec.duration)),
        )

    @staticmethod
    def _fit_duration(scenes: list[Scene], target: float) -> None:
        """Nudge scene lengths until the clip lands near its promised runtime.

        The model routinely under-shoots the brief; stretching every scene by
        the same factor keeps the pacing it wrote while hitting the format.
        """
        total = sum(scene.duration for scene in scenes)
        if total <= 0:
            return
        low, high = target * 0.9, target * 1.18
        if low <= total <= high:
            return
        factor = max(0.75, min(1.45, target / total))
        for scene in scenes:
            # Never trim below the reading floor: a shorter clip is not worth
            # a scene nobody can finish.
            floor = reading_time(scene)
            scene.duration = round(min(6.5, max(floor, scene.duration * factor)), 2)

    @staticmethod
    def _logo_bytes(knowledge: KnowledgeBase | None) -> bytes | None:
        if not knowledge or not knowledge.logo_url or "/media/" not in knowledge.logo_url:
            return None
        path = get_storage().root / knowledge.logo_url.split("/media/", 1)[1]
        try:
            return path.read_bytes()
        except OSError:
            return None

    @staticmethod
    def _music():
        root = get_storage().root / "brand" / "music"
        try:
            tracks = sorted(p for p in root.iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav"))
        except OSError:
            return None
        return tracks[0] if tracks else None
