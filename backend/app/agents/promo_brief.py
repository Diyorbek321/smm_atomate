"""Builds a clip by *sequencing* scene archetypes, rather than filling one family.

:mod:`app.agents.promo` picks one of ten authored videos and fills its slots.
That ceiling is visible in the output: every educational clip a business ships
is the same video with different words in it.

This agent picks a *sequence* instead — scenes drawn from eleven archetypes —
so structure varies with the subject while every individual scene stays
authored. The model still emits no geometry: it names archetypes and writes
copy, exactly as before.

That fixed the ceiling one layer down and rebuilt it here: the prompt carried a
single seven-beat skeleton, so every clip still opened on a number and closed
the same way, and only the wording moved. :mod:`app.services.promo_variety`
holds the skeleton pool and this agent picks from it against what the business
already shipped — so the shape of the argument varies too, and a clip that
comes out looking like last week's is sent back for a rewrite.

The scene catalogue is read from ``assets/promo/scenes``, so adding a scene type
is one JSON file and a line of copy schema — no change here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.base import BaseAgent, knowledge_context
from app.agents.promo import short
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.models.business import Business
from app.models.knowledge_base import KnowledgeBase
from app.services.promo_families import Brand
from app.services.promo_scenes import (
    MOODS,
    WPM,
    archetype_names,
    build_script,
    catalogue,
    needs_still,
)
from app.services.promo_variety import (
    HISTORY,
    Shape,
    Skeleton,
    avoid_note,
    choose,
    choose_backdrop,
    too_close,
)

log = get_logger(__name__)

#: Scenes per clip when neither the caller nor the skeleton has an opinion.
#: Eight lands between 50 and 90 seconds at the delivery rate the narration is
#: written for. Each skeleton now carries its own count instead — a countdown
#: needs room to count and a question does not, and holding every clip to one
#: length is a pattern a viewer reads before the first line lands.
SCENES = 8

#: Rewrites allowed before giving up. One more than the family agent, because
#: there are now two reasons to reject a draft — scenes that failed validation,
#: and a clip too close in shape to the last one — and a validation failure
#: should not spend the budget the repetition check needs.
ATTEMPTS = 3

#: A clip whose scenes mostly failed validation is not worth rendering; below
#: this share of good scenes the attempt is thrown away.
MIN_GOOD = 0.5

#: Photo scenes per clip. A clip that is all photographs has traded one kind of
#: sameness for another — the rhythm that reads as *edited* is picture, card,
#: picture, and the authored graphic scenes are what supply the card.
MAX_STILLS = 3

#: The graphic scene each photo scene degrades into: same copy fields, no
#: picture. Used when the shelf is empty and when a model asks for more
#: photographs than a clip should carry. Degrading beats dropping — the clip
#: keeps its argument and loses only its texture.
STILL_TWIN: dict[str, str] = {"kadr": "matn", "kadrstat": "stat",
                              "belgilar": "royxat"}

SYSTEM = """Sen — o'zbek tilida qisqa vertikal video (Reels/Shorts) ssenariy yozuvchisan.

Sening ishing ikkitasi: KATALOGDAN sahna turlarini tanlash va ularga matn yozish.
Joylashuv, rang, vaqt, animatsiya — hammasi tayyor. Sen ularni o'ylamaysan.

QOIDALAR:
- Til: o'zbekcha (lotin). Jonli og'zaki nutq, ruschadan tarjima emas.
- Yangi sahna turini O'YLAB TOPMA — faqat katalogdagilardan tanla.
- `say` — ovoz aytadigan gap. `text` — ekranda ko'rinadigan yozuv.
  Ular bir-biriga mos, lekin AYNAN bir xil emas: ekrandagi matn qisqaroq.
- Har `say` da 1-2 ta muhim so'zni *yulduzcha* ichiga ol.
- Raqamni aniq ber: «68 foiz», «3.4 barobar» — «ko'p» emas.
- Raqam va faktni faqat bilim bazasidan ol, o'ylab topma.
- Raqobatchini tilga olma. Aniq daromad va'da qilma."""

def _no_docstring(schema: dict[str, Any]) -> None:
    """Keep a class docstring out of the response schema.

    Pydantic publishes `__doc__` as the object's `description`, and the schema
    has a hard budget (see :class:`SceneCopy`) that three hundred characters of
    rationale eats a fifth of. The docstring is for whoever reads this file.
    """
    schema.pop("description", None)


class SceneCopy(BaseModel):
    """Every field any archetype can ask for — one field per *meaning*.

    Not one field per archetype, and the descriptions are terse, because the
    response schema has a budget: past roughly a dozen fields at this nesting
    depth Gemini returns `INVALID_ARGUMENT` with no detail — and the clip
    silently falls through to a weaker provider. Eleven archetypes named
    separately, described properly, is three times over it.

    So fields that mean the same thing share one name — a cta's headline, a
    table's title and a stat's label are all `title` — and :data:`_FIELDS` maps
    each back to whatever its archetype calls it. What each field is *for*
    belongs in the prompt, which has room for it.
    """

    model_config = ConfigDict(json_schema_extra=_no_docstring)

    title: short(28) = ""
    caption: short(48) = ""
    quote: short(120) = ""
    author: short(28) = ""
    #: Not `int | None`: an optional integer becomes `anyOf: [integer, null]`,
    #: which Gemini rejects outright. Zero reads as "not provided".
    to: int = Field(default=0, ge=0)
    suffix: short(3, "% yoki +") = ""
    left_title: short(22) = ""
    left_body: short(90) = ""
    right_title: short(22) = ""
    right_body: short(90) = ""
    #: The only list in the schema, and it has to stay that way: a second
    #: array — an array of objects especially — makes Gemini reject the whole
    #: response schema with `INVALID_ARGUMENT`. A table's rows travel through
    #: here as "nom: qiymat" strings and are split in :func:`_copy_for`.
    items: list[short(46)] = Field(default_factory=list, max_length=5)


class BriefScene(BaseModel):
    use: short(16)
    say: short(320)
    text: SceneCopy = Field(default_factory=SceneCopy)


class BriefPlan(BaseModel):
    mood: short(12) = "qorongu"
    scenes: list[BriefScene] = Field(min_length=3, max_length=12)


@dataclass(slots=True)
class BriefPlanned:
    """A validated clip, decided but not yet voiced or rendered.

    Everything expensive and everything random has already happened: the model
    has been asked, the scenes validated, the skeleton and pictures chosen, the
    repetition guard satisfied. What is left is narration and pixels.

    It exists so the owner can be handed the lines to read *before* a voice is
    put on them. Recording your own narration means seeing the script first,
    and a plan that only lives inside one `write()` call cannot be shown to
    anybody.
    """

    job: dict[str, Any]
    shape: Shape
    dropped: list[str] = field(default_factory=list)

    @property
    def says(self) -> list[str]:
        return [str(line) for line in (self.job.get("say") or [])]


@dataclass(slots=True)
class BriefScript:
    script: dict
    used: list[str]
    #: Scenes dropped in validation. Worth surfacing: a clip that keeps losing
    #: the same archetype means its copy schema or its prompt line is wrong.
    dropped: list[str]
    #: What shape this clip turned out to be. Travels back to the caller rather
    #: than being written here: only a clip that actually rendered belongs in
    #: the history the next one is measured against, and this agent does not
    #: know whether the render succeeded.
    shape: Shape = field(default_factory=Shape)


#: Which schema field each archetype reads, and what the archetype calls it.
#: One entry per archetype, and the test suite checks that every `needs` line
#: in `assets/promo/scenes` is reachable from here — a new archetype with no
#: mapping is one a model can never fill.
_FIELDS: dict[str, dict[str, str]] = {
    "auditoriya": {"items": "items"},
    "belgilar":   {"items": "items"},
    "cta":        {"title": "headline"},
    "formula":    {"title": "title", "items": "items"},
    "iqtibos":    {"quote": "quote", "author": "author"},
    "kartochka":  {"left_title": "leftTitle", "left_body": "leftBody",
                   "right_title": "rightTitle", "right_body": "rightBody"},
    "kadr":       {},
    "kadrstat":   {"title": "label", "to": "to", "suffix": "suffix"},
    "matn":       {},
    "narx":       {"title": "title", "items": "rows"},
    "qadamlar":   {"title": "title", "items": "items"},
    "royxat":     {"title": "title", "items": "items"},
    "sanoq":      {"to": "to", "caption": "caption", "suffix": "suffix"},
    "sarlavha":   {"items": "lines"},
    "stat":       {"title": "label", "to": "to", "suffix": "suffix"},
    "taqqoslash": {"left_title": "leftTitle", "left_body": "leftBody",
                   "right_title": "rightTitle", "right_body": "rightBody"},
    "tuzatish":   {"caption": "setup", "title": "wrong", "left_title": "verdict"},
}

_LEADING_NUMBER = re.compile(r"^\s*\d+\s*[.)\-–—]\s*")

#: The last headline line reads as not-yet-said, so it sits back in grey.
_PENDING = "#A9ACB1"


def _copy_for(use: str, copy: SceneCopy) -> dict[str, Any]:
    """Model output, shaped the way this archetype's placeholders read it.

    Only the fields this archetype actually uses survive: a model that fills
    `quote` on a `cta` scene has written something nobody asked for, and it
    should not travel any further than here.
    """
    text: dict[str, Any] = {}
    for schema_field, archetype_field in _FIELDS.get(use, {}).items():
        value = getattr(copy, schema_field)
        # Falsy means absent for every field here — empty string, empty list,
        # and a counter left at zero all mean the model skipped this one.
        if value:
            text[archetype_field] = value

    if use == "sarlavha" and text.get("lines"):
        words = [{"text": str(w).upper()} for w in text["lines"]]
        words[-1] = {**words[-1], "color": _PENDING}
        text["lines"] = words
    if use in ("royxat", "qadamlar") and text.get("items"):
        # The archetype numbers the rows itself; a model that also numbers them
        # renders "1  1. Bir marta...".
        text["items"] = [_LEADING_NUMBER.sub("", str(i)) for i in text["items"]]
    # A word here renders glued to a 360px numeral — and `short` would have
    # trimmed "soat" to "soa" first. The unit belongs in the caption; only a
    # symbol sits against the number.
    if text.get("suffix") and any(c.isalpha() for c in text["suffix"]):
        text.pop("suffix")
    if use == "narx" and text.get("rows"):
        text["rows"] = [_row(str(r)) for r in text["rows"]]
    if use == "formula" and text.get("items"):
        text["items"] = [_beat(str(i)) for i in text["items"]]
    if use == "belgilar":
        text = _markers(text.pop("items", []))
    return text


#: How many callouts one frame can carry before it stops pointing at anything.
MAX_MARKERS = 3


def _markers(items: list[Any]) -> dict[str, Any]:
    """A list of "LABEL: note" strings, fanned out to the callout slots.

    Each callout is pinned to its own coordinate, so they cannot be one
    repeated line the way a list can — and asking the model for six separate
    fields to fill three of them is six ways to get it wrong. It writes one
    list; this puts each entry where the archetype expects it.
    """
    out: dict[str, Any] = {}
    for slot, raw in zip("abc", list(items)[:MAX_MARKERS], strict=False):
        label, _, note = str(raw).partition(":")
        out[f"{slot}_text"] = label.strip()
        if note.strip():
            out[f"{slot}_sub"] = note.strip()
    return out


def _beat(line: str) -> dict[str, str]:
    """"ANSWER: to'g'ridan-to'g'ri javob" -> one lettered row.

    The letter is taken from the word rather than asked for. A-R-E is the
    initials of Answer-Reason-Example, and every formula worth putting on
    screen works that way; asking a model for the letter separately buys a
    field that can disagree with the word beside it.
    """
    word, _, desc = line.partition(":")
    word = word.strip()
    return {"letter": word[:1].upper(), "word": word, "desc": desc.strip()}


def _row(line: str) -> dict[str, str]:
    """"Boshlang'ich: 490 ming" -> a table row.

    Rows arrive as strings because the schema may hold only one list; see
    :class:`SceneCopy`. A line with no separator becomes a label with no value
    rather than being dropped — half a row still reads.
    """
    left, _, right = line.partition(":")
    return {"left": left.strip(), "right": right.strip()}


def _missing(use: str, text: dict[str, Any]) -> list[str]:
    needs = next((a["needs"] for a in catalogue() if a["name"] == use), [])
    return [n.rstrip("[]") for n in needs
            if not n.endswith("?") and not text.get(n.rstrip("[]"))]


class PromoBriefAgent(BaseAgent):
    name = "promo_brief"
    #: One call decides the shape of a clip that costs minutes of browser time.
    #: The stronger model is close to free at that ratio and is measurably
    #: better at holding a multi-beat argument together — which matters more
    #: now that the beats differ per skeleton instead of always being the same
    #: seven.
    use_pro_model = True

    async def write(
        self,
        business: Business,
        knowledge: KnowledgeBase | None,
        topic: str,
        *,
        scenes: int = 0,
        mood: str | None = None,
        props: list[str] | None = None,
        voice: bool = False,
        recording: str | None = None,
    ) -> BriefScript:
        planned = await self.plan(business, knowledge, topic, scenes=scenes,
                                  mood=mood, props=props)
        brand = self._brand(business, knowledge, props)
        timing = await self._narrate(planned.job, voice, recording)
        script = build_script(planned.job, brand, timing=timing)
        used = [s["use"] for s in planned.job["scenes"]]
        log.info("promo_brief_written", scenes=len(used), dropped=len(planned.dropped),
                 seconds=script["duration"], mood=script["music"]["mood"],
                 skeleton=planned.shape.skeleton, voiced=len(timing))
        return BriefScript(script=script, used=used,
                           dropped=planned.dropped, shape=planned.shape)

    def _brand(self, business: Business, knowledge: KnowledgeBase | None,
               props: list[str] | None) -> Brand:
        return Brand.from_colors(
            dict(knowledge.brand_colors) if knowledge and knowledge.brand_colors else {},
            mark=business.name,
            props=props or [],
            cta=(knowledge.phone if knowledge else "") or "Batafsil",
        )

    async def plan(
        self,
        business: Business,
        knowledge: KnowledgeBase | None,
        topic: str,
        *,
        scenes: int = 0,
        mood: str | None = None,
        props: list[str] | None = None,
    ) -> BriefPlanned:
        """Decide the clip. No narration, no render, no pixels."""
        recent = await self._recent(business)
        skeleton = choose(recent, topic)
        library = self._library(business, knowledge)
        backdrop = self._backdrop(library, recent)
        # Stills come from the same shelf but never repeat the backdrop: the
        # picture behind the whole clip showing up again as a full-frame scene
        # is the clip quoting itself.
        stills = [path for path in library if path != backdrop]
        # An explicit `scenes` from the caller still wins — the API exposes it
        # and someone asking for a six-scene clip should get one — but the
        # default is now the skeleton's own length rather than a constant.
        count = scenes or skeleton.scenes
        system = await self.system_prompt(SYSTEM, business_id=business.id)
        prompt = self._prompt(business, knowledge, topic, count, skeleton, recent)

        complaints: list[str] = []
        for attempt in range(ATTEMPTS):
            plan = await self.ask_json(
                prompt if not complaints
                else f"{prompt}\n\nOLDINGI URINISH XATOSI: {'; '.join(complaints[:4])}"
                     "\nShu xatolarni takrorlama.",
                BriefPlan, system=system,
                temperature=0.85 if attempt == 0 else 0.6,
                max_tokens=4000,
            )
            job, dropped, complaints = self._job(plan, business, topic, mood,
                                                 skeleton, backdrop, stills)
            good = len(job["scenes"])
            if not good or good < (good + len(dropped)) * MIN_GOOD:
                log.warning("promo_brief_rejected", attempt=attempt + 1,
                            kept=good, dropped=len(dropped))
                continue

            used = [s["use"] for s in job["scenes"]]
            shape = Shape.of(skeleton, used, mood=str(job.get("mood", "")),
                             backdrop=Path(backdrop).name if backdrop else "")
            repeat = too_close(shape, recent)
            # Last attempt keeps what it has. A clip that rhymes with last
            # week's is a worse clip; no clip at all is a worse product, and
            # the owner is waiting on a render either way.
            if repeat and attempt < ATTEMPTS - 1:
                log.info("promo_brief_too_similar", attempt=attempt + 1,
                         skeleton=skeleton.name, reason=repeat)
                complaints = [repeat, *complaints]
                continue

            # Narration happens after this returns, and that ordering is the
            # point: the free tier is ten requests per model per day and one
            # clip spends one per scene, so a draft about to be thrown away for
            # repeating last week's shape must not cost a day's quota first.
            log.info("promo_brief_planned", scenes=good, dropped=len(dropped),
                     skeleton=skeleton.name, repeated=bool(repeat),
                     attempt=attempt + 1)
            return BriefPlanned(job=job, shape=shape, dropped=dropped)

        raise ProviderError(
            "promo_brief",
            "yaroqli sahna ketma-ketligi chiqmadi: " + "; ".join(complaints[:3]),
        )

    async def _recent(self, business: Business) -> list[Shape]:
        """What this business already shipped, or nothing when there is no db.

        The agent is constructed without a session in tests and in the one-off
        scripts, and a missing history is not an error — it is a new client.
        Failing the render because the memory could not be read would trade a
        cosmetic problem for an outage, so this swallows and logs.
        """
        if self.session is None:
            return []
        try:
            from app.repositories.clip_shape import ClipShapeRepository

            return await ClipShapeRepository(self.session).recent(
                business.id, limit=HISTORY
            )
        except Exception as exc:  # pragma: no cover - db shape is tested elsewhere
            log.warning("promo_history_unavailable", error=str(exc)[:200])
            return []

    def _prompt(self, business: Business, knowledge: KnowledgeBase | None,
                topic: str, scenes: int, skeleton: Skeleton,
                recent: list[Shape]) -> str:
        # The catalogue names the *schema* fields to fill, not the archetype's
        # own field names: the model can only write what the schema has.
        listing = "\n".join(
            f"  {a['name']} — {', '.join(_FIELDS.get(a['name'], {})) or 'matnsiz'} — {a['desc']}"
            for a in catalogue()
        )
        return "\n\n".join(filter(None, [
            knowledge_context(business, knowledge),
            "BILIM BAZASI — faqat fon: undan faqat shu mavzuga tegishli faktni ol.",
            f"KLIP MAVZUSI (har bir sahna aynan shu haqda bo'lsin): {topic}"
            if topic.strip() else "",
            f"SAHNA KATALOGI (nom — kerakli maydonlar — nima uchun)\n{listing}",
            f"TUZILISH — «{skeleton.name}» skeleti (moslashtir, ko'chirma)\n"
            f"{skeleton.beats}",
            f"BIRINCHI SAHNA aynan shu ishni qilsin: {skeleton.opening}. "
            "Boshqa ochilish bilan boshlama.",
            avoid_note(recent),
            f"Nutq tezligi ~{WPM} so'z/daqiqa. Ilgak 10-16 so'z, tushuntirish "
            f"20-40 so'z, sarlavha kartochkasi 3-5 so'z. Jami {scenes} ta sahna, "
            # Derived from the scene count rather than fixed at 60-90: the
            # skeletons are deliberately different lengths, and a six-scene
            # question stretched to ninety seconds is padding.
            f"video {scenes * 7}-{scenes * 11} soniya.",
            "Oxirgi sahna «cta» bo'lsin. Uning `title` i 1-3 so'z — brend "
            "imzosi kapsula sifatida o'zi qo'shiladi, uni takrorlama.",
            f"«kadr» va «kadrstat» — to'liq ekran fotosurat sahnalari. Rasmni "
            f"sen tanlamaysan, o'zi biriktiriladi. Klipda ko'pi bilan "
            f"{MAX_STILLS} ta bo'lsin: fotosurat va grafik sahna navbatlashsa "
            "montaj bo'ladi, hammasi fotosurat bo'lsa yana bir xillik.",
            "«narx» sahnasida har `items` bandi «nom: qiymat» ko'rinishida.",
            "`suffix` faqat belgi: % yoki +. O'lchov birligini (soat, kun, ta) "
            "`caption` ichida yoz — u raqamga yopishib chiqadi.",
            "`mood` — bittasi: " + " | ".join(sorted(MOODS)) + ".",
        ]))

    def _job(self, plan: BriefPlan, business: Business, topic: str,
             mood: str | None, skeleton: Skeleton | None = None,
             backdrop: str = "", stills: list[str] | None = None,
             ) -> tuple[dict[str, Any], list[str], list[str]]:
        """The model's plan, validated into a job the composer can build."""
        known = set(archetype_names())
        refs, says, texts = [], [], {}
        used_stills: list[str] = []
        dropped: list[str] = []
        complaints: list[str] = []

        for index, scene in enumerate(plan.scenes):
            if scene.use not in known:
                dropped.append(scene.use)
                complaints.append(f"«{scene.use}» degan sahna yo'q")
                continue
            # Which archetype actually renders is settled first, because
            # everything below resolves against it. The twins share their copy
            # fields today, so resolving in the old order happened to work;
            # relying on that would make the next pair a silent bug.
            #
            # The model names the archetype; the picture is attached here. A
            # model asked for a filename invents one, and a scene built around
            # a photograph that does not exist renders as a black rectangle.
            use = scene.use
            if needs_still(use):
                shelf = stills or []
                if not shelf or len(used_stills) >= MAX_STILLS:
                    twin = STILL_TWIN.get(use, "matn")
                    log.info("promo_still_degraded", wanted=use, chose=twin,
                             reason="shelf" if not shelf else "cap")
                    use = twin

            text = _copy_for(use, scene.text)
            gaps = _missing(use, text)
            if gaps or not scene.say.strip():
                dropped.append(use)
                complaints.append(
                    f"«{use}» sahnasida {', '.join(gaps or ['say'])} yo'q")
                continue

            slot = f"s{index}"
            ref: dict[str, Any] = {"use": use, "slot": slot, "say": len(says)}
            if needs_still(use):
                ref["still"] = {"src": stills[len(used_stills) % len(stills)]}
                used_stills.append(use)
            refs.append(ref)
            says.append(scene.say.strip())
            texts[slot] = text

        job = {
            "name": f"{business.id}-{abs(hash(topic)) % 10**8}",
            # Caller first — the API exposes `mood` and an explicit request
            # should win. Then the skeleton, because the feel is part of the
            # shape rather than a free choice made next to it; the model's own
            # `mood` is the fallback for a job built without a skeleton.
            "mood": mood or (skeleton.mood if skeleton else "") or plan.mood,
            "align": "center",
            "flash": 0,
            "scenes": refs, "say": says, "text": texts,
        }
        if skeleton is not None:
            job["transition"] = skeleton.transition
            job["entry"] = skeleton.entry
            job["bpm"] = skeleton.bpm
        if backdrop:
            job["background"] = backdrop
        return job, dropped, complaints

    async def _narrate(self, job: dict[str, Any], voice: bool,
                       recording: str | None = None) -> list[dict[str, Any]]:
        """Speak the clip's lines, or measure a take of somebody speaking them.

        A recording wins over the synthesiser whenever there is one, and it is
        not a fallback ordering — it is the better input. The edit is cut to
        measured delivery either way, so a real voice costs nothing in
        precision and no daily quota, and sounds like a person.

        Every failure here degrades rather than raises. A clip with no audio is
        what every clip was until recently; a clip that failed to render
        because a speech API was slow is a regression the owner feels the same
        day.
        """
        from app.services import tts

        says = [str(line) for line in (job.get("say") or [])]
        if not says:
            return []
        from app.services.storage import get_storage

        out_dir = Path(get_storage().root) / "vo" / str(job.get("name", "clip"))
        name = str(job.get("name", "clip"))

        if recording:
            try:
                lines = await tts.split(Path(recording), says, out_dir, name=name)
                log.info("promo_narration_own", lines=len(lines))
                return tts.as_timing(lines)
            except ValueError as exc:
                # The take does not match the script. Worth surfacing rather
                # than silently synthesising over the top of somebody's work.
                log.warning("promo_recording_mismatch", error=str(exc)[:200])
                return []
            except Exception as exc:
                log.warning("promo_recording_failed", error=str(exc)[:200])
                return []

        if not voice:
            return []
        if not tts.available():
            log.info("promo_narration_skipped", reason="no_key")
            return []
        try:
            lines = await tts.narrate(says, out_dir, name=name)
            return tts.as_timing(lines)
        except Exception as exc:
            log.warning("promo_narration_failed", error=str(exc)[:200])
            return []

    def _library(self, business: Business,
                 knowledge: KnowledgeBase | None) -> list[str]:
        """Every picture this clip may use, drawn on a cold shelf.

        Swallows its failures for the same reason :meth:`_recent` does: every
        clip before this one rendered on a flat colour, so an unreadable shelf
        costs a nicer clip and nothing else. A photo scene with nowhere to draw
        from is dropped in :meth:`_job` rather than rendered as a black hole.
        """
        try:
            from app.services.brand_assets import backdrop_library

            colors = (dict(knowledge.brand_colors)
                      if knowledge and knowledge.brand_colors else {})
            return [str(path) for path in backdrop_library(business.id, colors)]
        except Exception as exc:  # pragma: no cover - filesystem shape
            log.warning("promo_library_unavailable", error=str(exc)[:200])
            return []

    def _backdrop(self, library: list[str], recent: list[Shape]) -> str:
        """The picture behind this clip, rotated against the last ones."""
        names = [Path(path).name for path in library]
        picked = choose_backdrop(recent, names)
        return library[names.index(picked)] if picked else ""
