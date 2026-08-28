"""CopywriterAgent — native Uzbek captions for Telegram and Instagram."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.agents.base import BaseAgent, knowledge_context
from app.agents.facts import (
    Fact,
    collect_facts,
    mentions_a_fact,
    render_block,
    render_inline_block,
    retry_instruction,
)
from app.agents.prompts import COPYWRITER_SYSTEM, content_type_brief, pillar_brief
from app.core.logging import get_logger
from app.models.business import Business
from app.models.enums import ContentPillar, ContentType
from app.models.knowledge_base import KnowledgeBase
from app.schemas.content import CopyOutput, CopyOutputStrict
from app.services.brand_kit import kit_for
from app.utils.text import (
    IG_CAPTION_LIMIT,
    TG_MESSAGE_LIMIT,
    append_block,
    dedupe_phone,
    normalize_apostrophes,
    normalize_hashtags,
    strip_markdown_fences,
    truncate_caption,
)

log = get_logger(__name__)

#: How many slides/answers each format expects.
CAROUSEL_SLIDES = (5, 8)
QUIZ_ANSWERS = (3, 4)

#: How many past headlines are shown to the writer. Enough to reveal a pattern,
#: short enough that it does not crowd out the knowledge base and the facts.
HISTORY_LINES = 12


@dataclass(slots=True)
class CopyRequest:
    business: Business
    knowledge: KnowledgeBase | None
    content_type: ContentType
    pillar: ContentPillar
    topic: str
    angle: str = ""
    goal: str = ""
    extra_instructions: str = ""
    previous_caption: str = ""
    #: Headlines and topics this business already wrote in the last month.
    #: `previous_caption` covers one rewrite of one post; this covers the month,
    #: which is the scale at which a feed starts repeating itself.
    recent_headlines: list[str] = field(default_factory=list)


def _states_the_phone(caption: str, phone: str) -> bool:
    """Is this number already in the caption, however it was punctuated?"""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 7:
        return False
    return digits[-9:] in "".join(ch for ch in (caption or "") if ch.isdigit())


def _flatten(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _repeats(caption: str, block: str, phone: str = "") -> bool:
    """Would appending this block say something the caption already says?

    The model routinely writes its own CTA into the body and returns it again
    in `cta`; appending blindly is how a post ends up printing the same phone
    number twice.
    """
    if not block:
        return True
    if _flatten(block) in _flatten(caption):
        return True
    return bool(phone and _states_the_phone(block, phone) and _states_the_phone(caption, phone))


class CopywriterAgent(BaseAgent):
    name = "copywriter"

    async def run(self, request: CopyRequest) -> CopyOutput:
        system = await self.system_prompt(
            COPYWRITER_SYSTEM, business_id=request.business.id, pillar=request.pillar
        )
        facts = collect_facts(request.knowledge, request.topic)

        # Strict schema so structured-output mode can actually express
        # slides/quiz/script; converted back to the loose CopyOutput after.
        copy = self._post_process(
            (
                await self.ask_json(
                    self._build_prompt(request, facts),
                    CopyOutputStrict,
                    system=system,
                    temperature=0.95,
                    max_tokens=2500,
                )
            ).to_copy_output(),
            request,
        )

        # Small models drop the numbers even when asked; one sharper retry is
        # cheaper than a post the editor will score at 5.
        if not mentions_a_fact(copy.caption_tg, facts):
            log.info("copy_missing_facts_retrying", topic=request.topic[:60])
            retry = replace(
                request,
                extra_instructions=" ".join(
                    filter(None, [request.extra_instructions, retry_instruction(facts)])
                ),
            )
            copy = self._post_process(
                (
                    await self.ask_json(
                        self._build_prompt(retry, facts),
                        CopyOutputStrict,
                        system=system,
                        temperature=0.7,
                        max_tokens=2500,
                    )
                ).to_copy_output(),
                retry,
            )
            if not mentions_a_fact(copy.caption_tg, facts):
                # Two attempts is enough begging — state the facts ourselves so
                # the editor scores the post that actually ships.
                block = render_inline_block(facts)
                if block:
                    copy.caption_tg = append_block(copy.caption_tg, block)
                    copy.caption_ig = append_block(copy.caption_ig, block)
                    log.info("copy_facts_injected", topic=request.topic[:60])
                else:
                    log.warning("copy_still_fact_free", topic=request.topic[:60])

        return copy

    # ------------------------------------------------------------------ #
    def _build_prompt(self, request: CopyRequest, facts: list[Fact] | None = None) -> str:
        kb = request.knowledge
        blocks = [
            knowledge_context(request.business, kb),
            f"USTUN: {request.pillar.value}\n{pillar_brief(request.pillar)}",
            f"FORMAT: {request.content_type.value}\n{content_type_brief(request.content_type)}",
            f"MAVZU: {request.topic}",
        ]
        if request.angle:
            blocks.append(f"YONDASHUV: {request.angle}")
        if request.goal:
            blocks.append(f"MAQSAD: {request.goal}")
        if kb and kb.contact_line:
            blocks.append(f"ALOQA (CTA da ishlat):\n{kb.contact_line}")
        if kb and kb.preferred_hashtags:
            blocks.append("BREND HASHTAGLAR (birinchi bo'lib qo'y): " + " ".join(kb.preferred_hashtags[:5]))
        if kb and kb.banned_topics:
            blocks.append("TEGMA: " + ", ".join(kb.banned_topics))
        # The brand's own voice, above the house rules in the system prompt:
        # `casual` cannot tell a law firm from a bakery, and this can.
        if kb and (voice := kit_for(kb.brand_kit).voice.prompt_block()):
            blocks.append(voice)
        if request.previous_caption:
            blocks.append(
                "AVVALGI VARIANT (uni takrorlama, yaxshila):\n" + request.previous_caption[:1500]
            )
        if history := self._history_block(request.recent_headlines):
            blocks.append(history)
        if request.extra_instructions:
            blocks.append(f"QO'SHIMCHA KO'RSATMA (eng yuqori ustuvorlik): {request.extra_instructions}")

        # Placed last on purpose: it is the requirement most often ignored.
        if facts_block := render_block(facts or []):
            blocks.append(facts_block)

        blocks.append(self._output_contract(request.content_type))
        return "\n\n".join(blocks)

    @staticmethod
    def _history_block(headlines: list[str]) -> str:
        """The last month of openings, so this one does not become the twelfth.

        Trimmed hard on purpose. The point is to show the model the *shape* it
        keeps falling into — the same hook, the same four words — and a dozen
        short lines do that as well as sixty long ones at a fraction of the
        prompt. Anything past the first line of a headline is padding here.
        """
        seen: set[str] = set()
        lines: list[str] = []
        for headline in headlines:
            trimmed = " ".join((headline or "").split())[:90]
            key = trimmed.lower()
            if not trimmed or key in seen:
                continue
            seen.add(key)
            lines.append(f"- {trimmed}")
            if len(lines) >= HISTORY_LINES:
                break
        if not lines:
            return ""
        return (
            "SHU BRENDDA YAQINDA YOZILGAN SARLAVHALAR — bularning birortasini "
            "takrorlama, o'xshash ochilish va o'xshash burchakdan qoch:\n" + "\n".join(lines)
        )

    @staticmethod
    def _output_contract(content_type: ContentType) -> str:
        base = (
            "JSON qaytar: headline, hook, caption_tg, caption_ig, cta, hashtags"
        )
        if content_type == ContentType.CAROUSEL:
            return (
                base
                + f", slides ({CAROUSEL_SLIDES[0]}-{CAROUSEL_SLIDES[1]} ta, har biri "
                + '{"index":1,"title":"...","body":"..."}). '
                + "caption_tg/caption_ig — karusel ostidagi umumiy matn."
            )
        if content_type == ContentType.TELEGRAM_QUIZ:
            return (
                base
                + ', quiz {"question":"...","answers":["...","..."],"correct_option_id":0,"explanation":"..."}. '
                + f"{QUIZ_ANSWERS[0]}-{QUIZ_ANSWERS[1]} ta javob varianti bo'lsin. "
                + "caption_tg — quizdan oldin yuboriladigan qisqa kirish matni."
            )
        if content_type == ContentType.REELS_SCRIPT:
            return (
                base
                + ', script {"duration_sec":30,"voiceover":"...","scenes":[{"t":"0-3s",'
                + '"shot":"...","on_screen":"...","voice":"..."}]}.'
            )
        return base + "."

    # ------------------------------------------------------------------ #
    def _post_process(self, copy: CopyOutput, request: CopyRequest) -> CopyOutput:
        """Deterministic hygiene the model should not be trusted with."""
        kb = request.knowledge

        copy.headline = normalize_apostrophes(strip_markdown_fences(copy.headline))[:280]
        copy.hook = normalize_apostrophes(strip_markdown_fences(copy.hook))[:280]
        copy.cta = normalize_apostrophes(strip_markdown_fences(copy.cta))[:280]
        copy.caption_tg = normalize_apostrophes(strip_markdown_fences(copy.caption_tg))
        copy.caption_ig = normalize_apostrophes(strip_markdown_fences(copy.caption_ig))

        if not copy.caption_ig and copy.caption_tg:
            copy.caption_ig = copy.caption_tg
        if not copy.caption_tg and copy.caption_ig:
            copy.caption_tg = copy.caption_ig

        # Guarantee the CTA and contact block exist on both platforms — but the
        # model often writes the phone into its own CTA, and a caption showing
        # the same number twice reads as careless.
        phone = (kb.phone or "") if kb else ""
        for block in filter(None, [copy.cta, kb.contact_line if kb else ""]):
            if not _repeats(copy.caption_tg, block, phone):
                copy.caption_tg = append_block(copy.caption_tg, block)
            if not _repeats(copy.caption_ig, block, phone):
                copy.caption_ig = append_block(copy.caption_ig, block)

        if kb and kb.phone:
            copy.caption_tg = dedupe_phone(copy.caption_tg, kb.phone)
            copy.caption_ig = dedupe_phone(copy.caption_ig, kb.phone)

        brand_tags = kb.preferred_hashtags if kb else []
        copy.hashtags = normalize_hashtags(list(brand_tags) + list(copy.hashtags))
        if copy.hashtags:
            copy.caption_ig = append_block(copy.caption_ig, " ".join(copy.hashtags))

        copy.caption_tg = truncate_caption(copy.caption_tg, TG_MESSAGE_LIMIT)
        copy.caption_ig = truncate_caption(copy.caption_ig, IG_CAPTION_LIMIT)

        copy.slides = self._normalize_slides(copy.slides, request)
        copy.quiz = self._normalize_quiz(copy.quiz, request)
        return copy

    @staticmethod
    def _normalize_slides(slides: list[dict], request: CopyRequest) -> list[dict]:
        if request.content_type != ContentType.CAROUSEL:
            return []
        cleaned: list[dict] = []
        for slide in slides[: CAROUSEL_SLIDES[1]]:
            title = normalize_apostrophes(str(slide.get("title", ""))).strip()
            body = normalize_apostrophes(str(slide.get("body", ""))).strip()
            if not (title or body):
                continue
            # Index after filtering: slide numbering is rendered as "n/total".
            cleaned.append(
                {
                    "index": len(cleaned) + 1,
                    "title": truncate_caption(title, 60),
                    "body": truncate_caption(body, 200),
                    "bullets": [str(b)[:90] for b in (slide.get("bullets") or [])][:4],
                }
            )
        return cleaned

    @staticmethod
    def _normalize_quiz(quiz: dict, request: CopyRequest) -> dict:
        if request.content_type != ContentType.TELEGRAM_QUIZ:
            return {}
        answers = [normalize_apostrophes(str(a)).strip() for a in (quiz.get("answers") or []) if str(a).strip()]
        answers = [a[:95] for a in answers][: QUIZ_ANSWERS[1]]
        if len(answers) < 2:
            return {}
        correct = quiz.get("correct_option_id", 0)
        try:
            correct = int(correct)
        except (TypeError, ValueError):
            correct = 0
        return {
            "question": truncate_caption(normalize_apostrophes(str(quiz.get("question", request.topic))), 250),
            "answers": answers,
            "correct_option_id": correct if 0 <= correct < len(answers) else 0,
            "explanation": truncate_caption(normalize_apostrophes(str(quiz.get("explanation", ""))), 190),
        }
