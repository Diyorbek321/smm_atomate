"""Writes the copy for a Remotion promo; timing and layout are not its business.

Same contract as :mod:`app.agents.promo`: the model returns short Uzbek strings
into a fixed schema, :mod:`app.services.remotion_script` turns them into a
beat-locked script, and the render service draws it. Nothing the model writes
can move an element or change a cut.

One extra guard lives here because this engine has a scene the others do not:
the big counting number. A number on screen reads as a fact, so it is kept only
when it literally appears in the business's own knowledge base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

from app.agents.base import BaseAgent, knowledge_context
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.models.business import Business
from app.models.knowledge_base import KnowledgeBase
from app.services.music import energy_for, mood_for
from app.services.promo_families import Brand
from app.services.remotion_script import ICONS, FeatureCopy, PromoCopy, build_script, pattern_for

log = get_logger(__name__)

ATTEMPTS = 2
PLACEHOLDER = re.compile(r"\[[^\]]*\]|\{\{|\}\}|lorem|xxx", re.IGNORECASE)

SYSTEM = """Sen — mahalliy biznes uchun 30-50 soniyalik vertikal reklama video matnini yozasan.
Sening ishing FAQAT matn. Dizayn, animatsiya, vaqt, musiqa — hammasi tayyor.

QOIDALAR:
- O'zbekcha (lotin), sodda, jonli. Shtamp va quruq reklama gaplari yo'q.
- Har maydonning uzunlik chegarasiga qat'iy amal qil — ekranga katta harfda chiqadi.
- hook: 2-3 ta juda qisqa savol yoki holat (tomoshabin o'zini taniydi).
- punch: hookka javob beradigan 1-2 so'zli zarba ibora.
- accent maydonlari: sarlavhaning ICHIDAGI so'z(lar)ni aynan takrorla.
- Raqam, narx, fakt faqat bilim bazasidan. Bilmasang stat_value = 0.
- Kontakt (telefon, manzil) yozma — u alohida qo'yiladi."""


def text(limit: int, description: str = "") -> Any:
    """A string the model is *asked* to keep under `limit` — never cut here.

    :func:`app.agents.promo.short` trims to the limit, which is fine for a
    template that can absorb it but cuts words in half on a full-screen
    headline ("xushmuomala hayd"). Overflow is reported back to the model
    instead (:func:`overflows`) and, if it persists, trimmed on a word
    boundary (:func:`fitted`).
    """
    hint = f"{description} (≤{limit} belgi)".strip()
    return Annotated[str, BeforeValidator(lambda value: str(value).strip()), Field(description=hint)]


#: Screen budgets, in characters. The layout also auto-sizes, so these are
#: about reading time as much as about width.
LIMITS = {"hook": 18, "lead": 28, "punch": 18, "tagline": 34, "list_title": 24,
          "list_accent": 14, "items": 30, "stat_suffix": 3, "stat_label": 30,
          "cta_tagline": 38, "cta_accent": 24, "button": 28}
FEATURE_LIMITS = {"label": 14, "title": 30, "accent": 16, "subtitle": 56}
#: How far past its budget a line may run once the retry is spent. The scenes
#: shrink type to fit, so a slightly long line costs a little size; cutting it
#: costs meaning ("Mashina kutyapsizmi?" -> "Mashina").
SLACK = 1.5


def _icon(value: Any) -> str:
    text = str(value).strip().lower()
    return text if text in ICONS else "star"


Icon = Annotated[str, BeforeValidator(_icon),
                 Field(description=f"bittasi: {', '.join(ICONS)}")]


class FeatureSchema(BaseModel):
    label: text(FEATURE_LIMITS["label"], "bitta so'z, masalan: Tezkor")
    title: text(FEATURE_LIMITS["title"], "2-4 so'zli sarlavha")
    accent: text(FEATURE_LIMITS["accent"], "sarlavhadagi urg'u so'zi")
    subtitle: text(FEATURE_LIMITS["subtitle"], "bitta izoh gapi")
    icon: Icon


class RemotionCopySchema(BaseModel):
    hook: list[text(LIMITS["hook"])] = Field(min_length=2, max_length=3)
    lead: text(LIMITS["lead"], "punch oldidagi kichik qator, bo'sh bo'lishi mumkin")
    punch: text(LIMITS["punch"])
    tagline: text(LIMITS["tagline"], "brend shiori")
    features: list[FeatureSchema] = Field(min_length=1, max_length=3)
    list_title: text(LIMITS["list_title"], "masalan: Nega aynan biz?")
    list_accent: text(LIMITS["list_accent"])
    items: list[text(LIMITS["items"])] = Field(min_length=0, max_length=4)
    stat_value: int = Field(0, description="bilim bazasidagi aniq raqam, bo'lmasa 0")
    stat_suffix: text(LIMITS["stat_suffix"], "masalan: + yoki %")
    stat_label: text(LIMITS["stat_label"])
    cta_tagline: text(LIMITS["cta_tagline"])
    cta_accent: text(LIMITS["cta_accent"])
    button: text(LIMITS["button"], "harakatga chaqiruv tugmasi")


@dataclass(slots=True)
class RemotionScript:
    script: dict[str, Any]
    copy: PromoCopy


def contact_for(knowledge: KnowledgeBase | None) -> str:
    """One short on-screen contact: phone first, else the Telegram handle."""
    if knowledge is None:
        return ""
    if knowledge.phone:
        return knowledge.phone.strip()
    if knowledge.telegram_username:
        return "@" + knowledge.telegram_username.strip().lstrip("@")
    return ""


def grounded(value: int, context: str) -> bool:
    """True when `value` is written in the knowledge base (spaces/commas ignored)."""
    if value <= 0:
        return False
    digits = re.sub(r"(?<=\d)[\s,.](?=\d{3}\b)", "", context)
    return re.search(rf"(?<!\d){value}(?!\d)", digits) is not None


def problems(copy: RemotionCopySchema) -> list[str]:
    """Deterministic checks that the model cannot argue with."""
    found: list[str] = []
    texts = [*copy.hook, copy.punch, copy.tagline, copy.cta_tagline, copy.button,
             *(f.title for f in copy.features), *(f.subtitle for f in copy.features), *copy.items]
    if not copy.punch.strip() or not copy.button.strip():
        found.append("punch va button bo'sh bo'lmasin")
    if any(not f.title.strip() for f in copy.features):
        found.append("har bir features.title to'ldirilsin")
    for text in texts:
        if PLACEHOLDER.search(text):
            found.append(f"to'ldirilmagan joy qoldi: «{text}»")
    return found


def clip_words(value: str, limit: int) -> str:
    """Shorten to `limit` on a word boundary; a lone over-long word is kept whole."""
    if len(value) <= limit:
        return value
    cut = value[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,—-")
    return cut if cut and len(cut) <= limit else value.split(" ", 1)[0]


def _over(value: str, limit: int) -> bool:
    return len(value) > limit


def overflows(copy: RemotionCopySchema) -> list[str]:
    """Fields longer than their screen budget, phrased as a complaint for the retry."""
    found: list[str] = []
    for name, limit in LIMITS.items():
        values = getattr(copy, name)
        for value in values if isinstance(values, list) else [values]:
            if _over(value, limit):
                found.append(f"{name} «{value}» {limit} belgidan uzun — qisqaroq so'z tanla")
    for feature in copy.features:
        for name, limit in FEATURE_LIMITS.items():
            if _over(getattr(feature, name), limit):
                found.append(f"features.{name} «{getattr(feature, name)}» {limit} belgidan uzun")
    return found


def fitted(copy: RemotionCopySchema) -> RemotionCopySchema:
    """A copy with no field past SLACK x its budget — cut between words, never inside one."""
    def fit(value: str, limit: int) -> str:
        return clip_words(value, int(limit * SLACK))

    update: dict[str, Any] = {}
    for name, limit in LIMITS.items():
        values = getattr(copy, name)
        update[name] = [fit(v, limit) for v in values] if isinstance(values, list) else fit(values, limit)
    update["features"] = [
        feature.model_copy(update={n: fit(getattr(feature, n), lim)
                                   for n, lim in FEATURE_LIMITS.items()})
        for feature in copy.features
    ]
    return copy.model_copy(update=update)


def to_copy(schema: RemotionCopySchema, context: str) -> PromoCopy:
    stat = schema.stat_value if grounded(schema.stat_value, context) else 0
    if schema.stat_value and not stat:
        log.info("remotion_stat_dropped", value=schema.stat_value, reason="not in knowledge base")
    return PromoCopy(
        hook=list(schema.hook), lead=schema.lead, punch=schema.punch, tagline=schema.tagline,
        features=[FeatureCopy(f.label, f.title, f.accent, f.subtitle, f.icon) for f in schema.features],
        list_title=schema.list_title, list_accent=schema.list_accent, items=list(schema.items),
        stat_value=stat, stat_suffix=schema.stat_suffix, stat_label=schema.stat_label,
        cta_tagline=schema.cta_tagline, cta_accent=schema.cta_accent, button=schema.button,
    )


class RemotionPromoAgent(BaseAgent):
    name = "remotion_promo"
    #: One call per multi-minute render: the stronger model is close to free here.
    use_pro_model = True

    async def write(self, business: Business, knowledge: KnowledgeBase | None,
                    topic: str) -> RemotionScript:
        context = knowledge_context(business, knowledge)
        system = await self.system_prompt(SYSTEM, business_id=business.id)
        prompt = "\n\n".join(filter(None, [
            context,
            "BILIM BAZASI — faqat fon: undan faqat shu mavzuga tegishli faktni ol.",
            f"VIDEO MAVZUSI (hamma sahna shu haqda): {topic}" if topic.strip() else "",
            "Faqat so'ralgan maydonlarni JSON qilib qaytar.",
        ]))
        brand = Brand.from_colors(
            dict(knowledge.brand_colors) if knowledge and knowledge.brand_colors else {},
            mark=business.name, cta="Batafsil",
        )
        mood = mood_for(topic or business.name)
        complaints: list[str] = []

        for attempt in range(ATTEMPTS):
            schema = await self.ask_json(
                prompt if not complaints else f"{prompt}\n\nOLDINGI URINISH XATOSI: "
                + "; ".join(complaints) + "\nShu xatolarni takrorlama.",
                RemotionCopySchema, system=system,
                temperature=0.85 if attempt == 0 else 0.6, max_tokens=1400,
            )
            complaints = problems(schema)
            long_fields = overflows(schema)
            last = attempt == ATTEMPTS - 1
            if not complaints and (not long_fields or last):
                if long_fields:
                    log.warning("remotion_copy_trimmed", fields=long_fields[:3])
                copy = to_copy(fitted(schema), context)
                script = build_script(
                    copy, brand, name=business.name.upper(), contact=contact_for(knowledge),
                    pattern=pattern_for(business.name, str(business.category)),
                    mood=mood, energy=energy_for(mood),
                )
                log.info("remotion_script_written", scenes=len(script["props"]["scenes"]),
                         seconds=script["duration"], attempt=attempt + 1)
                return RemotionScript(script=script, copy=copy)
            complaints = complaints + long_fields
            log.warning("remotion_copy_rejected", attempt=attempt + 1, issues=complaints[:3])

        raise ProviderError("remotion_promo", "yaroqli matn chiqmadi: " + "; ".join(complaints[:3]))
