"""What has to change between two clips for one business, and what must not.

:mod:`app.services.promo_scenes` built the room to vary in: eleven archetypes,
eight scenes to a clip, more sequences than a business will ship in a year.
:mod:`app.agents.promo_brief` then put a single seven-beat skeleton in the
prompt above it and the room collapsed. Every clip opens on a number, names the
audience second and signs off the same way; the archetypes underneath do move,
and nobody watching can tell, because structure is what a viewer remembers and
wording is what they don't.

:mod:`app.utils.similarity` already stops a *caption* repeating itself. Nothing
watched the shape, so the shape repeated freely — which is the layer that
actually reads as "same video again".

So the skeleton becomes a variable. Six of them, each with its own opening move
and its own length, picked against what this business already shipped instead
of fixed in the prompt.

The outline was only the first constant. Three more sat beside it, each one a
capability that was built, wired into the template, and then pinned:

* **Motion.** ``template.html`` implements five scene transitions and five line
  entries. All eleven archetypes declare ``transition: cut`` and none sets
  ``entry``, so every clip hard-cut between scenes and every line rose from
  below. The vocabulary existed and was never spoken.
* **Music.** ``_music`` reads ``job["bpm"]``, which nothing ever set — every
  clip ran at 118 BPM. The older family engine varies tempo from 100 to 128;
  the archetype engine lost that when it replaced it.
* **Backdrop.** ``backdrops.py`` draws six motifs per client in their own
  palette, the template renders ``S.background`` with a Ken Burns move, and the
  composer never set it. Every scene was a flat brand colour.

Each is now a field on the skeleton, so the shape of the argument and the way
it looks and sounds agree with each other rather than being independently
constant.

What must **not** vary is the brand. Palette, type, voice, and the look
:mod:`app.services.style_dna` pins on purpose are the reason a feed reads as one
company; a clip that shares nothing with the last one is not variety, it is a
stranger. The line this module draws is narrow and deliberate — the brand holds
still, the argument's shape moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.core.logging import get_logger
from app.utils.text import fingerprint

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Skeleton:
    """One rhetorical shape a clip can take, and how it moves and sounds.

    ``scenes`` belongs here rather than on the caller: a countdown needs room
    to count and a question needs none, and holding every clip at eight scenes
    is its own kind of sameness — every video the same length is a pattern a
    viewer clocks before the first line lands.

    Motion and tempo live here for the same reason they were worth unpinning at
    all: they are not decoration on top of the argument, they *are* how the
    argument reads. A countdown that slides sideways and a story that dissolves
    are making their structure visible. Scattering these across the file as
    independent rotations would give variety without meaning — six shapes each
    dressed at random, which is noise, not range.
    """

    name: str
    #: The move the opening scene makes. Two clips can differ everywhere else
    #: and still feel identical if they both start by reciting a statistic, so
    #: this is scored separately from the skeleton it belongs to.
    opening: str
    scenes: int
    beats: str
    #: Scene-to-scene motion. `template.html` knows cut · none · slide · wipe,
    #: and treats anything else as its default whip.
    transition: str
    #: How a line arrives. `entryTransform` knows rise · scale · slideX · flip
    #: · mask.
    entry: str
    bpm: int
    #: Uzbek mood name from :data:`app.services.promo_scenes.MOODS`, which maps
    #: it to one of the four synthesised beds.
    mood: str


#: The pool. Order is not priority — :func:`choose` reads history, not this
#: list — but `dalil` stays first because it is the shape the prompt used to
#: hard-code, and keeping it in the pool means the change adds shapes rather
#: than trading one fixed skeleton for another.
SKELETONS: tuple[Skeleton, ...] = (
    Skeleton(
        name="dalil",
        opening="raqamli ilgak",
        scenes=8,
        transition="whip",
        entry="rise",
        bpm=120,
        mood="qorongu",
        # the original feel: an argument that keeps shoving forward
        beats="""1 aniq raqamli ilgak
2 auditoriyani nomlash — tomoshabin o'zini tanisin
3 muammo qayerdan kelib chiqadi — ayblamasdan
4 tomoshabin allaqachon kelgan noto'g'ri xulosa
5 burilish: «muammo bunda emas» + eng ko'pi uch sabab
6 kim gapiryapti / nega ishonish mumkin
7 taklif va bitta aniq harakat""",
    ),
    Skeleton(
        name="hikoya",
        opening="bitta odam, bitta lahza",
        scenes=7,
        transition="none",
        entry="scale",
        bpm=104,
        mood="hikoya",
        # a story dissolves rather than cuts; scenes grow into frame
        beats="""1 bitta odam, bitta lahza — roli va aniq vaqti bilan
2 u nima qilmoqchi edi
3 nima to'sqinlik qildi — aniq tafsilot, umumiy gap emas
4 burilish nuqtasi: nima o'zgardi
5 natija — raqam bilan
6 bu bitta odamning hikoyasi emas: shu holat ko'pchilikda
7 taklif va bitta aniq harakat""",
    ),
    Skeleton(
        name="teskari",
        opening="sanoq va'dasi",
        scenes=9,
        transition="slide",
        entry="slideX",
        bpm=126,
        mood="keskin",
        # a countdown pushes sideways, and the tempo counts with it
        beats="""1 sanoq va'dasi: «Uch xato — oxirgisi eng qimmatga tushadi»
2 uchinchi xato — eng yengili
3 u qanday pul yeydi
4 ikkinchi xato
5 u nega ko'proq turadi
6 birinchi xato — eng og'iri va kutilmagani
7 uchalasi bitta sababdan chiqadi
8 taklif va bitta aniq harakat""",
    ),
    Skeleton(
        name="savol",
        opening="tomoshabin savoli",
        scenes=6,
        transition="wipe",
        entry="mask",
        bpm=118,
        mood="qorongu",
        # a question is answered by uncovering it — wipe in, mask on
        beats="""1 tomoshabin haqiqatan so'raydigan savol — uning o'z so'zlari bilan
2 qisqa to'g'ridan-to'g'ri javob, chaynalmasdan
3 javobning isboti: raqam yoki aniq misol
4 «ha, lekin...» — darhol keladigan ikkinchi savol
5 unga ham javob
6 taklif va bitta aniq harakat""",
    ),
    Skeleton(
        name="qiyos",
        opening="hozirgi holat",
        scenes=8,
        transition="cut",
        entry="flip",
        bpm=112,
        mood="iliq",
        # two sides, hard cut between them; the flip shows both faces
        beats="""1 hozir qanday — tanish holat, ayblovsiz
2 u nimaga tushadi: vaqt yoki pul, aniq raqam bilan
3 qanday bo'lishi mumkin edi
4 ikkisi yonma-yon — farq raqamda ko'rinsin
5 farqni nima yaratadi — mexanizm, va'da emas
6 buni allaqachon qilgan kim bor
7 nimadan boshlanadi
8 taklif va bitta aniq harakat""",
    ),
    Skeleton(
        name="fakt",
        opening="yolg'iz jumla",
        scenes=10,
        transition="none",
        entry="mask",
        bpm=100,
        mood="minimal",
        # one fact, held: the slowest bed here, and nothing arrives fast
        beats="""1 bitta jumla, boshqa hech narsa — eng kuchli fakt
2 shu faktni ushlab turish: qo'shimcha izoh yo'q
3 bu raqam qayerdan olingan
4 birinchi tomoni — u nimani anglatadi
5 ikkinchi tomoni — kim uchun bu yomon xabar
6 uchinchi tomoni — kim uchun bu imkoniyat
7 shuning uchun biz shunday ishlaymiz
8 taklif va bitta aniq harakat""",
    ),
)

BY_NAME: dict[str, Skeleton] = {s.name: s for s in SKELETONS}

#: How many past clips are read back. Six covers a fortnight at the volume a
#: single business ships, and it is also the size of the pool — read fewer and
#: a skeleton could never age out of the "recently used" set.
HISTORY = 6

#: What makes two clips the same clip.
#:
#: `opening` is scored *only when the skeletons differ*, and that exception is
#: the whole subtlety here. Every skeleton in the pool carries its own opening,
#: so scoring both against a shared skeleton counts one fact twice — enough on
#: its own to trip any sane threshold, which would flag every legitimate
#: rotation reuse and burn a retry on it. Two *different* skeletons that
#: nonetheless start with the same move is a real signal and nothing else
#: catches it, so it keeps a small weight of its own.
WEIGHTS: dict[str, float] = {"skeleton": 0.5, "opening": 0.2, "archetypes": 0.5}

#: Above this a candidate is a recent clip wearing new words. Placed so that
#: reusing a skeleton (0.5) is fine on its own — with six shapes and a rotation
#: that is the system working — but reusing one *and* most of its scene order
#: is not.
TOO_CLOSE = 0.7

#: The guard looks back less far than the chooser. :func:`choose` reads six so a
#: skeleton can age out; the guard reads three because a shape reused after
#: five other clips is rotation, not repetition, and flagging it would reject
#: drafts for doing exactly what the rotation asked them to.
GUARD_WINDOW = 3


@dataclass(frozen=True, slots=True)
class Shape:
    """The structural fingerprint of one clip — everything but its words.

    Deliberately not the copy. Whether two clips *said* the same thing is
    :mod:`app.utils.similarity`'s question and it already answers it; this is
    the other half, and the half that was missing.
    """

    skeleton: str = ""
    opening: str = ""
    archetypes: tuple[str, ...] = ()
    scenes: int = 0
    mood: str = ""
    #: Filename of the backdrop this clip ran on. Tracked separately from the
    #: skeleton because it rotates on its own axis: two clips can share a shape
    #: legitimately, but running the same picture behind both is the kind of
    #: sameness a viewer notices before the first word.
    backdrop: str = ""

    @classmethod
    def of(cls, skeleton: Skeleton, used: list[str], mood: str = "",
           backdrop: str = "") -> Shape:
        return cls(
            skeleton=skeleton.name,
            opening=skeleton.opening,
            archetypes=tuple(used),
            scenes=len(used),
            mood=mood,
            backdrop=backdrop,
        )

    @classmethod
    def from_row(cls, row: Any) -> Shape:
        """A stored row read back. Tolerant on purpose: a shape recorded by an
        older build is missing fields, and a partial history is worth more than
        an exception on the generation path.
        """
        return cls(
            skeleton=str(getattr(row, "skeleton", "") or ""),
            opening=str(getattr(row, "opening", "") or ""),
            archetypes=tuple(str(a) for a in (getattr(row, "archetypes", None) or [])),
            scenes=int(getattr(row, "scenes", 0) or 0),
            mood=str(getattr(row, "mood", "") or ""),
            backdrop=str(getattr(row, "backdrop", "") or ""),
        )


def _sequence_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    """How much of one archetype sequence reads as the other, order included.

    Set overlap is the obvious measure and it is wrong here: `stat → matn →
    cta` and `cta → matn → stat` use the same three scenes and are not the same
    clip. Order is most of what distinguishes them, so the comparison is a
    sequence match rather than a set one.
    """
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, list(left), list(right)).ratio()


def closeness(candidate: Shape, previous: Shape) -> float:
    """0.0 – 1.0. How much of the previous clip the candidate repeats."""
    score = 0.0
    same_skeleton = bool(candidate.skeleton) and candidate.skeleton == previous.skeleton
    if same_skeleton:
        score += WEIGHTS["skeleton"]
    elif candidate.opening and candidate.opening == previous.opening:
        score += WEIGHTS["opening"]
    score += WEIGHTS["archetypes"] * _sequence_overlap(
        candidate.archetypes, previous.archetypes
    )
    return round(min(score, 1.0), 3)


def too_close(candidate: Shape, recent: list[Shape]) -> str:
    """The complaint to hand back for a rewrite, or `""` when the clip is new.

    A sentence rather than a boolean because it goes straight into the retry
    prompt, and "too similar" is not an instruction a model can act on.
    """
    for previous in recent[:GUARD_WINDOW]:
        overlap = _sequence_overlap(candidate.archetypes, previous.archetypes)
        score = closeness(candidate, previous)
        # An identical scene order is the same clip whatever the beats above it
        # say — the viewer sees the cards, not the outline — so it fails on its
        # own rather than waiting for the weighted score to agree.
        identical = bool(candidate.archetypes) and (
            candidate.archetypes == previous.archetypes
        )
        if not identical and score < TOO_CLOSE:
            continue
        shared = []
        if candidate.skeleton == previous.skeleton:
            shared.append(f"skelet «{previous.skeleton}»")
        elif candidate.opening == previous.opening:
            shared.append(f"ochilish «{previous.opening}»")
        if overlap > 0.6:
            shared.append("sahnalar ketma-ketligi: "
                          + " → ".join(previous.archetypes[:5]))
        return (
            "bu klip oxirgi kliplardan biriga juda o'xshab qoldi ("
            + ", ".join(shared or ["umumiy tuzilish"])
            + f", yaqinlik {score}) — boshqacha boshla va boshqa sahnalarni tanla"
        )
    return ""


def choose(recent: list[Shape], topic: str = "") -> Skeleton:
    """The shape this clip takes: whichever has been unused longest.

    ``recent`` is newest first, so a skeleton's position in it *is* its age;
    one that does not appear has never been used and outranks everything that
    has. Ties — the common case on a new business, where nothing has been used
    — break on the topic rather than on list order, because breaking them on
    order would hand every first clip the same skeleton and reintroduce the
    bug one level up.
    """
    used_at: dict[str, int] = {}
    for index, shape in enumerate(recent):
        used_at.setdefault(shape.skeleton, index)

    offset = fingerprint(topic) if topic.strip() else 0
    best, best_key = SKELETONS[0], (-1, -1)
    for index, skeleton in enumerate(SKELETONS):
        # Never used ranks above everything used, hence the len(recent) floor.
        age = used_at.get(skeleton.name, len(recent) + 1)
        key = (age, (index + offset) % len(SKELETONS))
        if key > best_key:
            best, best_key = skeleton, key

    log.info("promo_skeleton_chosen", skeleton=best.name, scenes=best.scenes,
             history=len(recent))
    return best


def choose_backdrop(recent: list[Shape], available: list[str]) -> str:
    """Which picture runs behind this clip: the one unused longest.

    Same rule as :func:`choose` and for the same reason, but on its own axis —
    the backdrop library is six motifs and the skeleton pool is six shapes, and
    tying them together would mean `dalil` always ran on the same picture, so
    every repeat of a shape would be a repeat of the whole look.

    Returns `""` when the business has no library yet; a flat brand colour is
    what the clip rendered on before any of this and remains a valid answer.
    """
    if not available:
        return ""
    used_at: dict[str, int] = {}
    for index, shape in enumerate(recent):
        if shape.backdrop:
            used_at.setdefault(shape.backdrop, index)
    # Ordered, not `max(key=...)`: ties have to resolve to the first candidate
    # in library order so a business with one clip of history gets a stable
    # answer rather than one that depends on dict iteration.
    return max(available, key=lambda name: (used_at.get(name, len(recent) + 1),
                                            -available.index(name)))


def avoid_note(recent: list[Shape]) -> str:
    """What the last clips did, written for the model as a thing not to repeat.

    Naming the openings separately from the skeletons matters: the failure this
    guards against is six clips that all start by reciting a number, which is
    invisible in a list of skeleton names alone.
    """
    if not recent:
        return ""
    lines = [
        f"  - skelet «{shape.skeleton or '?'}», ochilish «{shape.opening or '?'}»"
        + (f", sahnalar: {' → '.join(shape.archetypes[:5])}" if shape.archetypes else "")
        for shape in recent[:HISTORY]
    ]
    openings = [s.opening for s in recent[:HISTORY] if s.opening]
    warning = ""
    if len(openings) >= 2 and len(set(openings)) == 1:
        warning = (
            f"\nOxirgi {len(openings)} klip bir xil boshlangan («{openings[0]}»). "
            "Bu safar boshqacha boshla — birinchi sahna boshqa ish qilsin."
        )
    return (
        "SHU BIZNES OXIRGI KLIPLARI — TAKRORLAMA (yangisidan eskisiga):\n"
        + "\n".join(lines)
        + warning
    )
