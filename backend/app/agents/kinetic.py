"""KineticAgent — writes a scene script and renders an agency-style promo.

Two lengths share one engine. The short mode is the reference genre: one
phrase per scene, 12-18 seconds, made for feeds and stories. The long mode
adds numbered chapters and figure scenes so a minute holds together, and
leaves room for a voice-over the owner records afterwards.

The LLM only writes the script; the visuals are deterministic
(:mod:`app.services.kinetic`), so a clip is always on-brand and free to render.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent, knowledge_context
from app.core.logging import get_logger
from app.models.business import Business
from app.models.knowledge_base import KnowledgeBase
from app.services.brand_assets import photo_library, prop_library
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


def fallback_script(topic: str, business_name: str, length: str) -> list[Scene]:
    """LLM'siz ham klip chiqadi — deterministik zaxira ssenariy."""
    head = topic or "Yangiliklarimiz bor"
    scenes = [
        Scene(kind="text", text=head, accent=head.split()[-1], duration=2.3),
        Scene(kind="text", text="Sifatli ta'lim — yaqin joyda", accent="ta'lim", duration=1.9),
        Scene(kind="prop", text="Bizni ko'ring", accent="ko'ring", sub=business_name, duration=2.2),
        Scene(kind="text", text="Joylar soni cheklangan", accent="cheklangan", duration=1.9),
    ]
    if length == "long":
        scenes = [
            Scene(kind="text", text=head, accent=head.split()[-1], duration=2.4),
            Scene(kind="chapter", value="01", text="Yo'nalishlar", duration=1.8),
            Scene(kind="text", text="Til, matematika va IT", accent="IT", duration=2.3),
            Scene(kind="prop", text="Zamonaviy sinflar", accent="Zamonaviy", duration=2.5),
            Scene(kind="chapter", value="02", text="Ustozlar", duration=1.8),
            Scene(kind="stat", value="10 yil", text="tajriba", duration=2.4),
            Scene(kind="text", text="Har bir o'quvchiga alohida e'tibor", accent="alohida",
                  duration=2.4),
            Scene(kind="chapter", value="03", text="Natija", duration=1.8),
            Scene(kind="text", text="Bilim — kelajak poydevori", accent="poydevori", duration=2.4),
            Scene(kind="text", text="Bugun qadam tashlang", accent="Bugun", duration=2.2),
        ]
    return scenes


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
            scenes = fallback_script(topic, business.name, length)

        # The outro card is deterministic — never trusted to the model.
        scenes.append(
            Scene(kind="outro", text=business.name, sub="Bilim Shahri sizni kutmoqda", duration=2.6)
        )

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
