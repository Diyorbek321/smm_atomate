"""HTML/CSS → PNG rendering for stories, carousels and quote cards.

Playwright (headless Chromium) is the primary engine; when the browser binary
is unavailable we degrade gracefully to a Pillow-drawn card so the pipeline
never blocks on a missing system dependency.
"""

from __future__ import annotations

import asyncio
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.logging import get_logger
from app.services.storage import StoredFile, get_storage

log = get_logger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

#: Canvas sizes per format.
CANVAS = {
    "story": (1080, 1920),
    "carousel": (1080, 1350),
    "square": (1080, 1080),
    "portrait": (1080, 1350),
}

DEFAULT_COLORS = {
    "bg": "#0B0D12",
    "surface": "#151922",
    "text": "#F5F7FA",
    "primary": "#1E2A44",
    "accent": "#4F8CFF",
    "on_accent": "#0B0D12",
}


def layout_for(width: int, height: int) -> dict[str, int]:
    """Scale typography with the canvas so both formats stay balanced."""
    scale = width / 1080
    tall = height >= 1600
    return {
        "padding": int(80 * scale),
        "brand_size": int(30 * scale),
        "logo_size": int(72 * scale),
        "pill_size": int(26 * scale),
        "title_size": int((104 if tall else 88) * scale),
        "body_size": int((40 if tall else 36) * scale),
        "footer_size": int(28 * scale),
    }


def merge_colors(brand_colors: dict[str, Any] | None) -> dict[str, str]:
    colors = dict(DEFAULT_COLORS)
    for key, value in (brand_colors or {}).items():
        if isinstance(value, str) and value.startswith("#") and key in DEFAULT_COLORS:
            colors[key] = value
    return colors


@dataclass(slots=True)
class RenderRequest:
    template: str                       # story.html | carousel_slide.html | quote_card.html
    context: dict[str, Any]
    width: int = 1080
    height: int = 1350


class HtmlRenderer:
    """Single shared Chromium instance, lazily started, safely reusable."""

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._playwright: Any = None
        self._browser: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()
        self._unavailable = False

    # ------------------------------------------------------------------ #
    def render_html(self, request: RenderRequest) -> str:
        template = self._env.get_template(request.template)
        context = dict(request.context)
        context.setdefault("colors", DEFAULT_COLORS)
        context.setdefault("layout", layout_for(request.width, request.height))
        return template.render(**context)

    async def _browser_instance(self) -> Any:
        # A Playwright browser can only be driven from the event loop that
        # started it. One loop per process is the norm, but a second loop
        # (tests, an embedded runner) would otherwise hang forever, so detect
        # the change and start fresh instead.
        running = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not running:
            log.warning("renderer_loop_changed_restarting")
            self._browser = None
            self._playwright = None
            self._loop = None
            self._lock = asyncio.Lock()

        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            from playwright.async_api import async_playwright

            playwright = await async_playwright().start()
            try:
                self._browser = await playwright.chromium.launch(
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"]
                )
            except Exception:
                # Stop the driver process, otherwise a failed launch leaks it.
                await playwright.stop()
                raise
            self._playwright = playwright
            self._loop = running
            log.info("renderer_browser_started")
            return self._browser

    async def render_png(self, request: RenderRequest) -> bytes:
        html = self.render_html(request)
        if self._unavailable:
            return _pillow_card(request)
        try:
            browser = await self._browser_instance()
            page = await browser.new_page(
                viewport={"width": request.width, "height": request.height}, device_scale_factor=1
            )
            try:
                await page.set_content(html, wait_until="load", timeout=20_000)
                await page.wait_for_timeout(120)  # let webfonts settle
                return await page.screenshot(type="png")
            finally:
                await page.close()
        except Exception as exc:
            log.error("renderer_failed_fallback_pillow", error=str(exc)[:300])
            self._unavailable = True
            return _pillow_card(request)

    async def render_to_storage(self, request: RenderRequest, *, prefix: str = "card") -> StoredFile:
        data = await self.render_png(request)
        return get_storage().save_bytes(data, prefix=prefix, content_type="image/png")

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            self._loop = None


def _pillow_card(request: RenderRequest) -> bytes:
    """Minimal but presentable fallback card drawn with Pillow."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    ctx = request.context
    colors = ctx.get("colors") or DEFAULT_COLORS
    width, height = request.width, request.height
    image = Image.new("RGB", (width, height), colors["bg"])
    draw = ImageDraw.Draw(image)

    # Diagonal accent wash.
    accent = tuple(int(colors["accent"].lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    bg = tuple(int(colors["bg"].lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    for y in range(height):
        ratio = (y / height) * 0.35
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(bg[i] + (accent[i] - bg[i]) * ratio) for i in range(3)),
        )

    def _font(size: int) -> Any:
        for candidate in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ):
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size)
        return ImageFont.load_default()

    pad = int(80 * width / 1080)
    y = pad
    brand = str(ctx.get("brand", ""))[:40]
    if brand:
        draw.text((pad, y), brand.upper(), font=_font(int(34 * width / 1080)), fill=colors["accent"])
        y += int(90 * width / 1080)

    title = str(ctx.get("title") or ctx.get("quote") or "")
    title_font = _font(int(76 * width / 1080))
    for line in textwrap.wrap(title, width=22)[:6]:
        draw.text((pad, y), line, font=title_font, fill=colors["text"])
        y += int(92 * width / 1080)

    body = str(ctx.get("body") or ctx.get("highlight") or "")
    if body:
        y += int(30 * width / 1080)
        body_font = _font(int(38 * width / 1080))
        for line in textwrap.wrap(body, width=42)[:8]:
            draw.text((pad, y), line, font=body_font, fill=colors["text"])
            y += int(52 * width / 1080)

    contact = str(ctx.get("contact") or "")
    if contact:
        draw.text(
            (pad, height - pad - int(40 * width / 1080)),
            contact.replace("\n", "  •  ")[:90],
            font=_font(int(30 * width / 1080)),
            fill=colors["accent"],
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


_renderer: HtmlRenderer | None = None


def get_renderer() -> HtmlRenderer:
    global _renderer
    if _renderer is None:
        _renderer = HtmlRenderer()
    return _renderer


async def close_renderer() -> None:
    global _renderer
    if _renderer is not None:
        await _renderer.close()
        _renderer = None
