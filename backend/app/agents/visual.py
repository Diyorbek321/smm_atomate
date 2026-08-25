"""VisualAgent — Flux prompts + HTML/CSS card rendering for every format."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.agents.prompts import VISUAL_SYSTEM
from app.core.exceptions import ConfigurationError, ProviderError
from app.core.logging import get_logger
from app.models.business import Business
from app.models.enums import ContentPillar, ContentType
from app.models.knowledge_base import KnowledgeBase
from app.services.brand_assets import photo_library
from app.services.image_gen import DEFAULT_NEGATIVE, get_image_generator
from app.services.renderer import (
    CANVAS,
    RenderRequest,
    fonts_for,
    get_renderer,
    layout_for,
    merge_colors,
)
from app.services.storage import get_storage
from app.services.style_dna import StyleDNA, apply_style, style_for
from app.services.visual_qc import VisualVerdict, review_image
from app.services.visual_repair import diagnose, repair
from app.utils.text import truncate_caption

log = get_logger(__name__)

#: Cards are rendered via `set_content`, so the logo cannot be fetched over
#: HTTP — it is inlined as a data URI. Cap the payload to keep renders fast.
MAX_LOGO_BYTES = 500_000


def logo_data_uri(kb: KnowledgeBase | None) -> str:
    """Inline the business logo stored under /media for the card templates."""
    if kb is None or not kb.logo_url or "/media/" not in kb.logo_url:
        return ""
    relative = kb.logo_url.split("/media/", 1)[1]
    path = get_storage().root / relative
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if not data or len(data) > MAX_LOGO_BYTES:
        return ""
    mime = "image/png" if relative.lower().endswith(".png") else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


#: Real photos of the business live here; cards use them as backgrounds so the
#: feed shows actual classrooms and people instead of plain text cards.
BRAND_PHOTO_DIR = "brand/photos"
MAX_PHOTO_BYTES = 900_000


def pick_brand_photo_path(seed: str, business_id=None) -> Path | None:
    """Deterministically pick one library photo per topic.

    Seeding by topic keeps regenerations of the same post on the same photo
    while different topics rotate through the library.
    """
    files = photo_library(business_id, seed)
    if not files:
        return None
    index = int(hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest(), 16) % len(files)
    return files[index]


def pick_brand_photo(seed: str, business_id=None) -> str:
    """Same pick as :func:`pick_brand_photo_path`, inlined as a data URI."""
    path = pick_brand_photo_path(seed, business_id)
    if path is None:
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if not data or len(data) > MAX_PHOTO_BYTES:
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"

#: Aspect ratio used per content type.
RATIO_BY_TYPE = {
    ContentType.FEED_POST: "4:5",
    ContentType.CAROUSEL: "4:5",
    ContentType.STORY: "9:16",
    ContentType.TELEGRAM_QUIZ: "1:1",
    ContentType.REELS_SCRIPT: "9:16",
    ContentType.VIDEO_POST: "9:16",
}

MAX_CAROUSEL_SLIDES = 10

#: Renders per card. Three is one original plus two targeted repairs — past
#: that the reviewer has objected to something no lever here can move, and a
#: fourth render is a fourth model call spent proving it.
MAX_RENDER_ATTEMPTS = 3


def _topic_seed(topic: str) -> int:
    """A stable second seed per topic, so a retry is reproducible."""
    digest = hashlib.md5((topic or "post").encode(), usedforsecurity=False).hexdigest()
    return int(digest[:8], 16)

#: Cards are customer-facing, so the pillar tag has to be in the brand language
#: — "SALES" printed on an Uzbek post reads like a leftover debug label.
PILLAR_KICKERS: dict[ContentPillar, str] = {
    ContentPillar.SALES: "Qabul ochiq",
    ContentPillar.EDUCATIONAL: "Foydali",
    ContentPillar.SOCIAL_PROOF: "Natija",
    ContentPillar.INTERACTIVE: "Savol",
}

#: Short button labels; the full call to action lives in the caption.
CTA_BUTTONS: dict[ContentPillar, str] = {
    ContentPillar.SALES: "Yozilish",
    ContentPillar.EDUCATIONAL: "Batafsil",
    ContentPillar.SOCIAL_PROOF: "Siz ham",
    ContentPillar.INTERACTIVE: "Javob bering",
}


def cta_button(pillar: ContentPillar) -> str:
    return CTA_BUTTONS.get(pillar, "Batafsil")


def _design_block(design: Any | None) -> str:
    """The designer's composition, as instructions the art director must honour.

    Kept as a plain duck-typed read rather than an import so the visual agent
    carries no dependency on the designer: with the agent switched off this is
    one empty string that `filter(None, ...)` drops from the prompt.
    """
    if design is None:
        return ""
    layout = getattr(design, "layout", "")
    if not layout:
        return ""

    lines = [f"Composition (decided upstream, follow it): layout={layout}"]
    focal = getattr(design, "focal", "")
    if focal:
        lines.append(f"Single focal element: {focal}")
    accent_on = getattr(design, "accent_on", "")
    if accent_on and accent_on != "none":
        lines.append(f"The accent color belongs to: {accent_on}")
    density = getattr(design, "density", "")
    if density:
        lines.append(f"Density: {density}")
    if getattr(design, "photo_needed", True) is False:
        lines.append("No photograph — this is a typographic card. Return an empty image_prompt.")
    return "\n".join(lines)


class VisualBrief(BaseModel):
    """What the art-director agent returns."""

    image_prompt: str = Field(default="", description="English Flux prompt, 40-70 words, no text in image")
    negative_prompt: str = ""
    card_text: str = Field(default="", description="Short Uzbek headline for the overlay card, max 60 chars")
    card_body: str = Field(default="", description="Supporting line for the card, max 140 chars")
    highlight: str = Field(default="", description="Number/price to emphasise, e.g. '600 000 so'm'")


@dataclass(slots=True)
class VisualRequest:
    business: Business
    knowledge: KnowledgeBase | None
    content_type: ContentType
    pillar: ContentPillar
    topic: str
    headline: str = ""
    hook: str = ""
    cta: str = ""
    slides: list[dict] = field(default_factory=list)
    quote: dict | None = None
    generate_photo: bool = True
    #: Composition decided upstream by :class:`app.agents.designer.DesignerAgent`.
    #: ``None`` when that agent is disabled or failed — the brief is written the
    #: same way it always was.
    design: Any | None = None


@dataclass(slots=True)
class VisualOutput:
    image_url: str | None = None
    image_prompt: str | None = None
    video_url: str | None = None
    slides: list[dict] = field(default_factory=list)
    rendered_with: str = "none"          # flux | card | photo_card | video | none
    warnings: list[str] = field(default_factory=list)


class VisualAgent(BaseAgent):
    name = "visual"

    async def run(self, request: VisualRequest) -> VisualOutput:
        brief = await self._brief(request)
        output = VisualOutput(image_prompt=brief.image_prompt or None)

        if request.content_type == ContentType.CAROUSEL:
            output.slides = await self._render_carousel(request, brief, output.warnings)
            output.image_url = output.slides[0]["image_url"] if output.slides else None
            output.rendered_with = "card"
            return output

        if request.content_type == ContentType.TELEGRAM_QUIZ:
            # Polls carry no media on Telegram — skip rendering entirely.
            output.rendered_with = "none"
            return output

        photo = pick_brand_photo(request.topic or request.headline or "post", request.business.id)

        if request.content_type in (ContentType.STORY, ContentType.REELS_SCRIPT):
            template = "photo_card.html" if photo else "story.html"
            output.image_url = await self._render_card(
                request, brief, template=template, canvas="story", photo=photo,
                warnings=output.warnings,
            )
            output.rendered_with = "photo_card" if photo else "card"
            if request.content_type == ContentType.STORY:
                # Stories become motion clips when ffmpeg + a background exist;
                # the rendered card stays as the poster / fallback image.
                output.video_url = await self._render_video(request, brief)
                if output.video_url:
                    output.rendered_with = "video"
            return output

        # feed_post. Which of the two wins is a tier decision, not a technical
        # one: a real photograph of this centre is worth more than any model
        # output, but only the top tier reliably has a photo library to draw
        # on. See `PlanCapabilities.prefers_real_photo`.
        prefer_real = request.business.capabilities.prefers_real_photo and bool(photo)

        if request.generate_photo and brief.image_prompt and not prefer_real:
            url = await self._generate_photo(request, brief, output.warnings)
            if url:
                output.image_url = url
                output.rendered_with = "flux"
                return output

        # Real photos of the business beat a plain text card every time.
        template = "photo_card.html" if photo else "story.html"
        output.image_url = await self._render_card(
            request, brief, template=template, canvas="carousel", photo=photo,
            warnings=output.warnings,
        )
        output.rendered_with = "photo_card" if photo else "card"
        return output

    # ------------------------------------------------------------------ #
    async def _brief(self, request: VisualRequest) -> VisualBrief:
        system = await self.system_prompt(VISUAL_SYSTEM, business_id=request.business.id, pillar=request.pillar)
        colors = merge_colors(request.knowledge.brand_colors if request.knowledge else None)
        prompt = "\n\n".join(
            filter(
                None,
                [
                    f"Business: {request.business.name} ({request.business.category})",
                    f"Audience: {request.business.target_audience or 'general local audience'}",
                    f"Post topic (Uzbek): {request.topic}",
                    f"Headline (Uzbek): {request.headline or request.hook}",
                    f"Content pillar: {request.pillar.value}",
                    f"Format: {request.content_type.value} ({RATIO_BY_TYPE[request.content_type]})",
                    f"Brand accent color: {colors['accent']}",
                    _design_block(request.design),
                    "Return JSON: image_prompt, negative_prompt, card_text, card_body, highlight.",
                ],
            )
        )
        try:
            return await self.ask_json(prompt, VisualBrief, system=system, temperature=0.8, max_tokens=900)
        except Exception as exc:
            log.warning("visual_brief_failed", error=str(exc)[:200])
            return VisualBrief(
                image_prompt="",
                card_text=truncate_caption(request.headline or request.topic, 60),
                card_body=truncate_caption(request.hook, 140),
            )

    def _card_context(
        self, request: VisualRequest, brief: VisualBrief, canvas: str, photo: str = ""
    ) -> dict:
        kb = request.knowledge
        width, height = CANVAS[canvas]
        title = truncate_caption(brief.card_text or request.headline or request.topic, 70)
        body = truncate_caption(brief.card_body or request.hook, 150)
        if body.strip().casefold() == title.strip().casefold():
            body = ""  # the model often echoes the headline — an empty line beats a duplicate
        return {
            "brand": request.business.name,
            "colors": merge_colors(kb.brand_colors if kb else None),
            "fonts": fonts_for(kb.brand_kit if kb else None),
            "logo": logo_data_uri(kb),
            "photo": photo,
            "layout": layout_for(width, height),
            "kicker": PILLAR_KICKERS.get(request.pillar, ""),
            "title": title,
            "body": body,
            "highlight": brief.highlight,
            "subhighlight": "",
            "cta": cta_button(request.pillar),
            "contact": (kb.contact_line.replace("\n", "   ") if kb and kb.contact_line else ""),
        }

    async def _render_video(self, request: VisualRequest, brief: VisualBrief) -> str | None:
        """Motion clip for the item — AI-animated when the tariff allows,
        the zero-cost zoom montage otherwise."""
        from app.services import video as video_service

        capabilities = request.business.capabilities
        if not capabilities.video:
            log.info("video_skipped_plan", plan=str(request.business.plan))
            return None
        if video_service.ffmpeg_path() is None:
            return None
        seed = request.topic or request.headline or "video"
        background = pick_brand_photo_path(seed, request.business.id)
        if background is None:
            return None

        kb = request.knowledge
        logo_bytes: bytes | None = None
        if kb and kb.logo_url and "/media/" in kb.logo_url:
            logo_path = get_storage().root / kb.logo_url.split("/media/", 1)[1]
            try:
                logo_bytes = logo_path.read_bytes()
            except OSError:
                logo_bytes = None

        colors = merge_colors(kb.brand_colors if kb else None)
        clip_brief = video_service.ClipBrief(
            title=truncate_caption(brief.card_text or request.headline or request.topic, 48),
            subtitle=truncate_caption(brief.card_body or request.hook, 90),
            phone=(kb.phone if kb else "") or "",
            footer=(kb.address if kb else "") or "",
        )

        # Pro tariff: animate the scene itself (Seedance et al.), then brand it.
        # The tier unlocks it; the per-business switch still has to be on, because
        # every AI clip costs real money.
        if capabilities.ai_video and (request.business.settings or {}).get("ai_video"):
            url = await self._render_ai_video(request, brief, background, clip_brief, colors, logo_bytes)
            if url:
                return url

        try:
            stored = await video_service.render_clip_to_storage(
                background,
                clip_brief,
                colors,
                logo_bytes,
                prefix=request.content_type.value,
            )
            return stored.url
        except Exception as exc:
            log.warning("video_render_failed", error=str(exc)[:300])
            return None

    async def _render_ai_video(
        self,
        request: VisualRequest,
        brief: VisualBrief,
        background,
        clip_brief,
        colors: dict,
        logo_bytes: bytes | None,
    ) -> str | None:
        """AI-animated scene with the brand overlay composited on top."""
        from app.services import video as video_service
        from app.services.video_gen import DEFAULT_MOTION_PROMPT, get_video_generator

        generator = get_video_generator()
        if not generator.enabled:
            log.info("ai_video_skipped_no_key")
            return None
        try:
            frame_uri = pick_brand_photo(
                request.topic or request.headline or "video", request.business.id
            )
            if not frame_uri:
                return None
            stored_ai = await generator.animate(
                frame_uri, brief.image_prompt or DEFAULT_MOTION_PROMPT, duration=6
            )
            overlay = video_service.build_overlay(clip_brief, colors, logo_bytes)
            branded = await video_service.overlay_on_video(stored_ai.path, overlay)
            stored = get_storage().save_bytes(
                branded, prefix=f"{request.content_type.value}-ai", content_type="video/mp4"
            )
            return stored.url
        except Exception as exc:
            log.warning("ai_video_failed_fallback_montage", error=str(exc)[:300])
            return None

    async def _generate_photo(
        self, request: VisualRequest, brief: VisualBrief, warnings: list[str]
    ) -> str | None:
        """Generate the photo; a rejected one gets exactly one more roll.

        Unlike a card, a diffusion model fails differently every time it is
        asked, so the retry is a different seed rather than different words.
        The seed is derived from the topic so a regenerated post keeps landing
        on the same second attempt instead of drifting.
        """
        generator = get_image_generator()
        model = request.business.capabilities.image_model or None
        seeds: tuple[int | None, ...] = (None, _topic_seed(request.topic))
        best: tuple[str, VisualVerdict] | None = None
        # Every photo for this business shares one palette, light and lens;
        # without that anchor twenty posts read as twenty different brands.
        prompt = apply_style(brief.image_prompt, self._style(request))

        for attempt, seed in enumerate(seeds, start=1):
            try:
                image = await generator.generate(
                    prompt,
                    aspect_ratio=RATIO_BY_TYPE[request.content_type],
                    negative_prompt=brief.negative_prompt or DEFAULT_NEGATIVE,
                    # The tier decides the sampler: a trial account can live
                    # with a 4-step render, a paying feed cannot.
                    model=model,
                    seed=seed,
                )
            except (ConfigurationError, ProviderError) as exc:
                warnings.append(f"image_generation_failed: {str(exc)[:200]}")
                log.warning("flux_failed_fallback_card", error=str(exc)[:200])
                return best[0] if best else None

            verdict = await self._review_stored(image)
            if verdict is None or verdict.acceptable:
                return image.url
            if best is None or verdict.score > best[1].score:
                best = (image.url, verdict)
            log.info("photo_qc_retry", attempt=attempt, score=verdict.score)

        if best is not None:
            warnings.append(f"visual_qc {best[1].score}/10: {'; '.join(best[1].issues[:2])}")
            return best[0]
        return None

    @staticmethod
    def _style(request: VisualRequest) -> StyleDNA:
        kb = request.knowledge
        return style_for(
            request.business.category,
            kb.brand_colors if kb else None,
            kb.visual_style if kb else None,
        )

    @staticmethod
    async def _review_stored(image) -> VisualVerdict | None:
        """Run the gate over a generated photo that storage already holds."""
        if image.stored is None:
            return None
        try:
            data = image.stored.path.read_bytes()
        except OSError:
            return None
        mime = "image/jpeg" if image.stored.path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        return await review_image(data, mime_type=mime)

    async def _render_checked(
        self,
        context: dict,
        *,
        template: str,
        width: int,
        height: int,
        prefix: str,
        warnings: list[str] | None = None,
        max_attempts: int = MAX_RENDER_ATTEMPTS,
    ) -> str | None:
        """Render, check, repair what the reviewer objected to, render again.

        The repair is chosen from the verdict rather than fixed in advance —
        see :mod:`app.services.visual_repair`. When no lever is left the best
        attempt still ships (a flawed card beats no card) and the owner is told
        what was wrong with it.
        """
        renderer = get_renderer()
        best: tuple[bytes, VisualVerdict | None] | None = None
        tried: set[str] = set()

        for attempt in range(1, max_attempts + 1):
            try:
                data = await renderer.render_png(
                    RenderRequest(template=template, context=context, width=width, height=height)
                )
            except Exception as exc:
                log.error("card_render_failed", error=str(exc)[:300], template=template)
                return None

            verdict = await review_image(data, expect_text=str(context.get("title", "")))
            if verdict is None or verdict.acceptable:
                best = (data, verdict)
                break
            if best is None or verdict.score > (best[1].score if best[1] else 0):
                best = (data, verdict)

            repaired = repair(context, verdict, tried)
            log.info(
                "render_qc_retry", prefix=prefix, attempt=attempt, score=verdict.score,
                defect=diagnose(verdict), issues=verdict.issues[:2],
                giving_up=repaired is None,
            )
            if repaired is None:
                break
            context = repaired

        if best is None:                          # pragma: no cover - loop always runs
            return None
        data, verdict = best
        if warnings is not None and verdict is not None and not verdict.acceptable:
            warnings.append(
                f"visual_qc {prefix} {verdict.score}/10: {'; '.join(verdict.issues[:2])}"
            )
        return get_storage().save_bytes(data, prefix=prefix, content_type="image/png").url
    async def _render_card(
        self,
        request: VisualRequest,
        brief: VisualBrief,
        *,
        template: str,
        canvas: str,
        photo: str = "",
        warnings: list[str] | None = None,
    ) -> str | None:
        width, height = CANVAS[canvas]
        return await self._render_checked(
            self._card_context(request, brief, canvas, photo=photo),
            template=template,
            width=width,
            height=height,
            prefix=request.content_type.value,
            warnings=warnings,
        )

    async def _render_carousel(
        self, request: VisualRequest, brief: VisualBrief, warnings: list[str] | None = None
    ) -> list[dict]:
        slides = request.slides[:MAX_CAROUSEL_SLIDES]
        if not slides:
            slides = [{"index": 1, "title": request.headline or request.topic, "body": request.hook}]

        width, height = CANVAS["carousel"]
        colors = merge_colors(request.knowledge.brand_colors if request.knowledge else None)
        kb = request.knowledge
        logo = logo_data_uri(kb)
        cover_photo = pick_brand_photo(
            request.topic or request.headline or "carousel", request.business.id
        )
        total = len(slides)
        rendered: list[dict] = []

        for position, slide in enumerate(slides, start=1):
            context = {
                "brand": request.business.name,
                "colors": colors,
                "logo": logo,
                # Only the cover gets the photo — inner slides stay clean for reading.
                "photo": cover_photo if position == 1 else "",
                "layout": layout_for(width, height),
                "index": position,
                "total": total,
                "pill": PILLAR_KICKERS.get(request.pillar, "") if position == 1 else "",
                "title": truncate_caption(str(slide.get("title", "")), 70),
                "body": truncate_caption(str(slide.get("body", "")), 220),
                "bullets": [str(b) for b in (slide.get("bullets") or [])][:4],
                "cta": cta_button(request.pillar),
                "contact": (kb.contact_line.replace("\n", "   ") if kb and kb.contact_line else ""),
            }
            url = await self._render_checked(
                context,
                template="carousel_slide.html",
                width=width,
                height=height,
                prefix=f"slide{position}",
                warnings=warnings,
            )
            rendered.append({**slide, "index": position, "image_url": url})

        return rendered
