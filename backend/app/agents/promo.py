"""Picks a promo family and writes the copy that fills it.

The division of labour is the point. :mod:`app.services.promo_families` owns
every layout decision — where text sits, how long a scene holds, which cut
lands on which beat. This agent owns none of them. It chooses a family from the
content pillar and returns short strings.

A model asked for scene geometry produces scene geometry that overflows,
collides, and lands off the beat. A model asked for five lines of Uzbek copy
produces five lines of Uzbek copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

from app.agents.base import BaseAgent, knowledge_context
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.models.business import Business
from app.models.enums import ContentPillar
from app.models.knowledge_base import KnowledgeBase
from app.services.promo_families import BUILDERS, Brand
from app.services.promo_qc import blocking, inspect, off_topic
from app.utils.text import fingerprint

log = get_logger(__name__)

#: Which family serves which strategic bucket. INTERACTIVE had no video format
#: at all before `savol`, which is why it is the only pillar with one option.
PILLAR_FAMILIES: dict[ContentPillar, list[str]] = {
    ContentPillar.SALES: ["statement", "raqam", "uzluksiz", "dastur", "muddat"],
    ContentPillar.EDUCATIONAL: ["sanoq", "taqqoslash"],
    ContentPillar.SOCIAL_PROOF: ["isbot", "ustoz"],
    ContentPillar.INTERACTIVE: ["savol"],
}

#: Families that cannot render without an asset the model does not supply.
#: Picking one with nothing to show would produce a clip with a hole in it, so
#: the agent falls back to the next family in the same pillar.
NEEDS_FOOTAGE = {"ustoz"}

#: Rewrites allowed before giving up. One retry catches the model having a
#: bad turn; a second would mostly buy latency.
ATTEMPTS = 2

SYSTEM = """Sen — o'zbek ta'lim markazi uchun qisqa video ssenariy yozuvchisan.
Sening ishing FAQAT matn yozish. Joylashuv, vaqt, rang, animatsiya — hammasi
allaqachon tayyor shablonda. Sen faqat bo'sh joylarni to'ldirasan.

QOIDALAR:
- Matn o'zbekcha, sodda, jonli. Reklama shtampi yo'q.
- Har maydon uchun berilgan uzunlik chegarasiga qat'iy amal qil.
- Raqam va faktni faqat bilim bazasidan ol, o'ylab topma.
- Bosh harflar bilan yozilishi so'ralgan joyda BOSH HARF ishlat."""


# Named objects rather than tuples. A `tuple[str, str, str]` becomes
# `prefixItems` in JSON Schema, and small models produce malformed output for
# it often enough that a whole clip fails on a positional array. Named fields
# cost a few tokens and are what the models are actually good at.

def short(limit: int, description: str = "") -> Any:
    """A string field that is *trimmed* to `limit`, never rejected for it.

    A `max_length` constraint becomes `maxLength` in the JSON schema the
    provider enforces, so a model going one character over fails the whole
    request — and with it the whole clip. The limit still belongs in the
    prompt, as guidance; enforcing it is our job, not the model's.

    Used as the annotation, not the default: ``title: short(18)``.
    """
    hint = f"{description} (≤{limit} belgi)".strip()
    return Annotated[
        str,
        BeforeValidator(lambda value: str(value).strip()[:limit]),
        Field(description=hint),
    ]


# Named objects rather than tuples. A `tuple[str, str, str]` becomes
# `prefixItems` in JSON Schema, and small models produce malformed output for
# it often enough that a whole clip fails on a positional array.
class ListItem(BaseModel):
    head: short(22, "sarlavha")
    wrong: short(44, "muammo")
    right: short(44, "yechim")


class Reason(BaseModel):
    word: short(11, "BOSH SO'Z")
    desc: short(34, "izoh")


class LetterRow(BaseModel):
    letter: short(1, "bitta harf yoki raqam")
    word: short(10, "BOSH HARFLI SO'Z")
    desc: short(30, "izoh")


class SanoqCopy(BaseModel):
    title: short(18, "masalan '5 ta xato'")
    subtitle: short(42)
    items: list[ListItem] = Field(min_length=3, max_length=6)


class TaqqoslashPair(BaseModel):
    wrong_label: short(22)
    wrong: short(26)
    right_label: short(22)
    right: list[short(40)] = Field(min_length=1, max_length=3)


class TaqqoslashCopy(BaseModel):
    title: list[short(18)] = Field(min_length=2, max_length=2, description="ikki qator")
    pairs: list[TaqqoslashPair] = Field(min_length=2, max_length=3)


class SavolCopy(BaseModel):
    title: list[short(16)] = Field(min_length=2, max_length=2, description="ikki qator")
    question: list[short(32)] = Field(min_length=1, max_length=2, description="savol")
    options: list[short(80)] = Field(min_length=3, max_length=3, description="uch variant")
    correct: int = Field(ge=0, le=2, description="to'g'ri variant indeksi")
    reasons: list[Reason] = Field(min_length=3, max_length=3)


class RaqamStat(BaseModel):
    value: int = Field(ge=0)
    suffix: short(2, "masalan +")
    label: short(40)


class RaqamCopy(BaseModel):
    title: short(16)
    stats: list[RaqamStat] = Field(min_length=2, max_length=3)


class StatementCopy(BaseModel):
    kicker: short(26)
    hook: list[short(14)] = Field(min_length=3, max_length=3, description="uch qator")
    problem: list[short(14)] = Field(min_length=3, max_length=3,
                                     description="uch qator, o'rtasi BOSH HARF")
    diagnosis: list[short(10)] = Field(min_length=3, max_length=3,
                                       description="uch qator, o'rtasi BOSH HARF")
    formula_title: short(26)
    formula: list[LetterRow] = Field(min_length=3, max_length=3)
    summary: list[short(18)] = Field(min_length=2, max_length=2, description="ikki qator")


class IsbotCopy(BaseModel):
    badge: short(14, "masalan 6.5 -> 7.5")
    quote: list[short(26)] = Field(min_length=2, max_length=4, description="iqtibos qatorlari")
    attribution: short(34)
    changed_title: short(22)
    changed: list[LetterRow] = Field(min_length=3, max_length=3)


class UstozCopy(BaseModel):
    title: short(16)
    subtitle: short(20)
    caption: short(44, "kadr ostidagi bir qator")


class UzluksizCopy(BaseModel):
    """Bitta uzluksiz sahna — matn to'planib boradi, hech qaysisi ketmaydi."""

    opening: short(14)
    middle: short(18)
    build: short(14)
    punch: short(14, "aksent rangdagi yakuniy so'z")
    tagline: short(52)


class DasturRow(BaseModel):
    left: short(26, "nom")
    right: short(12, "vaqt yoki narx")


class DasturGroup(BaseModel):
    title: short(26)
    rows: list[DasturRow] = Field(min_length=2, max_length=4)


class DasturCopy(BaseModel):
    title: short(12)
    subtitle: short(20)
    groups: list[DasturGroup] = Field(min_length=1, max_length=2)


class MuddatCopy(BaseModel):
    kicker: short(24)
    pressure: short(13, "bosim so'zi")
    count_from: int = Field(ge=1, le=999)
    count_to: int = Field(ge=0, le=998)
    count_label: short(14, "masalan joy qoldi")
    date_lead: short(12)
    date: short(13, "BOSH HARF, masalan 2-SENTABR")
    date_tail: short(24)


SCHEMAS: dict[str, type[BaseModel]] = {
    "sanoq": SanoqCopy, "taqqoslash": TaqqoslashCopy, "savol": SavolCopy,
    "raqam": RaqamCopy, "statement": StatementCopy, "isbot": IsbotCopy,
    "ustoz": UstozCopy, "uzluksiz": UzluksizCopy, "dastur": DasturCopy,
    "muddat": MuddatCopy,
}


@dataclass(slots=True)
class PromoScript:
    family: str
    script: dict


class PromoAgent(BaseAgent):
    name = "promo"
    #: One call renders one clip — minutes of browser time either way — so the
    #: stronger model is close to free here, and it is measurably better at
    #: staying on the brief it was given.
    use_pro_model = True

    @staticmethod
    def family_for(pillar: ContentPillar, seed: int = 0, topic: str = "") -> str:
        """Which layout this clip uses.

        Nothing the bot queues passes a seed, so this was ``options[0]`` every
        time: every educational clip a business ever made was a `sanoq` list,
        whatever it was about. The topic breaks the tie when the caller has no
        seed of its own — same subject, same layout; different subject,
        possibly a different one.
        """
        options = PILLAR_FAMILIES.get(pillar) or ["statement"]
        index = seed or (fingerprint(topic) if topic.strip() else 0)
        return options[index % len(options)]

    async def write(
        self,
        business: Business,
        knowledge: KnowledgeBase | None,
        topic: str,
        *,
        pillar: ContentPillar = ContentPillar.EDUCATIONAL,
        family: str | None = None,
        props: list[str] | None = None,
        photo: str | None = None,
        footage: str | None = None,
        seed: int = 0,
    ) -> PromoScript:
        chosen = family or self.family_for(pillar, seed, topic)
        if chosen in NEEDS_FOOTAGE and not footage:
            alternatives = [f for f in PILLAR_FAMILIES.get(pillar, []) if f not in NEEDS_FOOTAGE]
            fallback = alternatives[seed % len(alternatives)] if alternatives else "statement"
            log.info("promo_family_fallback", wanted=chosen, chose=fallback, reason="no footage")
            chosen = fallback
        schema = SCHEMAS[chosen]
        system = await self.system_prompt(SYSTEM, business_id=business.id)
        # The brief was already the last thing before the output instruction
        # and was still ignored: asked for a clip about a backend course this
        # returned the knowledge base's own subject — "SMMda 3 ta xato" —
        # three times out of three, on the small model and on the large one.
        # Position was not the problem. What fixed it was saying out loud what
        # the knowledge base is *for*: four thousand characters of it read as
        # the subject unless something tells the model it is background.
        prompt = "\n\n".join(filter(None, [
            knowledge_context(business, knowledge),
            f"SHABLON: {chosen}",
            "BILIM BAZASI — faqat fon: undan faqat shu mavzuga tegishli faktni ol.",
            f"KLIP MAVZUSI (har bir sahna aynan shu haqda bo'lsin): {topic}" if topic.strip() else "",
            "Faqat so'ralgan maydonlarni JSON qilib qaytar.",
        ]))
        brand = Brand.from_colors(
            dict(knowledge.brand_colors) if knowledge and knowledge.brand_colors else {},
            mark=business.name,
            props=props or [],
            cta=(knowledge.phone if knowledge else "") or "Batafsil",
        )
        # The gate runs before rendering, not after: a clip is minutes of
        # browser time, and blank or duplicated copy is cheap to catch here and
        # expensive to discover in the finished file.
        fatal: list[str] = []
        complaints: list[str] = []
        #: A script that renders but answers the wrong brief. Kept, because a
        #: clip about the wrong subject still beats no clip, and because the
        #: retry is allowed to come back worse.
        drifted_script: dict | None = None

        for attempt in range(ATTEMPTS):
            copy = await self.ask_json(
                prompt if not complaints else f"{prompt}\n\nOLDINGI URINISH XATOSI: "
                + "; ".join(complaints) + "\nShu xatolarni takrorlama.",
                schema, system=system,
                temperature=0.85 if attempt == 0 else 0.6,
                max_tokens=1400,
            )
            script = BUILDERS[chosen](brand, **self._payload(copy, chosen, business, photo, footage))
            issues = inspect(script)
            fatal = blocking(issues)
            for issue in issues:
                if not issue.blocking:
                    log.info("promo_copy_warn", family=chosen, detail=issue.detail)

            drifted = bool(topic.strip()) and off_topic(script, topic)
            if not fatal and not drifted:
                log.info("promo_script_written", family=chosen, pillar=str(pillar),
                         seconds=script["duration"], scenes=len(script["scenes"]),
                         attempt=attempt + 1)
                return PromoScript(family=chosen, script=script)
            if not fatal:
                drifted_script = script

            # Drifting off the brief is worth the retry we have already
            # budgeted, but never worth failing a clip over: the check is a
            # heuristic, and a wrong verdict must not cost the owner a render.
            complaints = fatal or [
                f"klip «{topic}» haqida emas edi — har bir sahna shu mavzuni gapirsin"
            ]
            log.warning("promo_copy_rejected", family=chosen, attempt=attempt + 1,
                        off_topic=drifted, issues=complaints[:3])

        if drifted_script is not None:
            log.warning("promo_off_topic_shipped", family=chosen, topic=topic[:60])
            return PromoScript(family=chosen, script=drifted_script)
        raise ProviderError(
            "promo",
            f"«{chosen}» uchun yaroqli matn chiqmadi: " + "; ".join(fatal[:3]),
        )

    @staticmethod
    def _payload(copy: BaseModel, family: str, business: Business,
                 photo: str | None, footage: str | None) -> dict[str, Any]:
        """Model output, shaped for the family builder."""
        payload = copy.model_dump()
        payload["headline"] = business.name.upper()[:12]
        # Builders take positional rows; the schema uses named fields because
        # that is what models emit reliably. Translate at the seam.
        for key, order in (("items", ("head", "wrong", "right")),
                           ("reasons", ("word", "desc")),
                           ("formula", ("letter", "word", "desc")),
                           ("changed", ("letter", "word", "desc"))):
            if key in payload:
                payload[key] = [tuple(row[field] for field in order) for row in payload[key]]
        if family == "isbot":
            payload["photo"] = photo
        if family == "ustoz":
            payload["footage"] = footage
        for key in ("pairs", "groups"):
            if key in payload:
                payload[key] = [row if isinstance(row, dict) else row.model_dump()
                                for row in payload[key]]
        return payload
