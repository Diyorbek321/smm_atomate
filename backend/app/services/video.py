"""Branded motion clips — brand photo + Ken Burns zoom + text overlay via ffmpeg.

No LLM and no paid API involved: the clip is deterministic montage over the
brand photo library, so an announcement video costs nothing and renders in
about a minute. Graceful degradation: no ffmpeg binary → the caller keeps the
photo card instead.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.exceptions import ConfigurationError, PublishError
from app.core.logging import get_logger
from app.services.storage import StoredFile, get_storage

log = get_logger(__name__)

WIDTH, HEIGHT = 1080, 1920                  # story/reels canvas
DEFAULT_DURATION_SEC = 8
FPS = 30
LOGO_SIZE = 200

_BOLD_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
_REGULAR_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def _font(size: int, *, bold: bool = True) -> ImageFont.ImageFont:
    for path in _BOLD_FONTS if bold else _REGULAR_FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = (value or "").lstrip("#")
    if len(value) != 6:
        return (255, 255, 255, alpha)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


@dataclass(slots=True)
class ClipBrief:
    """Everything the overlay needs — plain strings, already truncated."""

    title: str
    subtitle: str = ""
    phone: str = ""
    footer: str = ""


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> list[str]:
    """Greedy word wrap into at most two lines; the tail is ellipsised."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == 2:
                break
    if current and len(lines) < 2:
        lines.append(current)
    elif current:
        lines[-1] = lines[-1].rstrip(".…") + "…"
    return lines or [text[:20]]


def build_overlay(brief: ClipBrief, colors: dict[str, str], logo: bytes | None = None) -> bytes:
    """Transparent PNG with logo, title, subtitle and a phone button."""
    accent = _rgba(colors.get("accent", "#C9A227"))
    ink = _rgba(colors.get("text", "#F5F2EA"))
    ink_soft = _rgba(colors.get("text", "#F5F2EA"), 210)
    on_accent = _rgba(colors.get("on_accent", "#141414"))
    shade_rgb = _rgba(colors.get("bg", "#141414"))[:3]

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))

    # Bottom shade so text stays readable over any background.
    gradient = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(gradient)
    band = 760
    for i in range(band):
        alpha = int(205 * (i / band) ** 1.5)
        gdraw.line([(0, HEIGHT - band + i), (WIDTH, HEIGHT - band + i)], fill=(*shade_rgb, alpha))
    overlay = Image.alpha_composite(gradient, overlay)
    draw = ImageDraw.Draw(overlay)

    if logo:
        try:
            badge = Image.open(BytesIO(logo)).convert("RGB").resize((LOGO_SIZE, LOGO_SIZE))
            mask = Image.new("L", (LOGO_SIZE, LOGO_SIZE), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, LOGO_SIZE, LOGO_SIZE], radius=LOGO_SIZE * 18 // 100, fill=255
            )
            overlay.paste(badge, (WIDTH // 2 - LOGO_SIZE // 2, 150), mask)
        except OSError:
            log.warning("video_overlay_logo_unreadable")

    def center(text: str, y: int, font: Any, fill: tuple[int, int, int, int]) -> None:
        draw.text(((WIDTH - draw.textlength(text, font=font)) // 2, y), text, font=font, fill=fill)

    title_font = _font(104)
    lines = _wrap(draw, brief.title, title_font, WIDTH - 140)
    y = 1000 if len(lines) > 1 else 1060
    for index, line in enumerate(lines):
        center(line, y, title_font, accent if index == len(lines) - 1 else ink)
        y += 122

    draw.rounded_rectangle([WIDTH // 2 - 70, y + 24, WIDTH // 2 + 70, y + 32], radius=4, fill=accent)

    if brief.subtitle:
        sub_font = _font(44, bold=False)
        for line in _wrap(draw, brief.subtitle, sub_font, WIDTH - 160):
            center(line, y + 74, sub_font, ink_soft)
            y += 58

    if brief.phone:
        top = 1560
        draw.rounded_rectangle([WIDTH // 2 - 330, top, WIDTH // 2 + 330, top + 100], radius=22, fill=accent)
        phone_font = _font(52)
        center(brief.phone, top + 22, phone_font, on_accent)
        if brief.footer:
            center(brief.footer, top + 140, _font(36, bold=False), ink_soft)

    buffer = BytesIO()
    overlay.save(buffer, format="PNG")
    return buffer.getvalue()


async def render_clip(
    background: Path, overlay_png: bytes, *, duration: int = DEFAULT_DURATION_SEC
) -> bytes:
    """Ken Burns zoom over the background with the overlay fading in."""
    binary = ffmpeg_path()
    if binary is None:
        raise ConfigurationError("ffmpeg is not installed — video rendering unavailable")

    frames = duration * FPS
    filter_complex = (
        f"[0:v]scale={int(WIDTH * 1.2)}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"zoompan=z='min(zoom+0.0007,1.16)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}[bgv];"
        "[1:v]format=rgba,fade=t=in:st=0.9:d=1.1:alpha=1[ov];"
        f"[bgv][ov]overlay=0:0,format=yuv420p,"
        f"fade=t=in:st=0:d=0.6,fade=t=out:st={duration - 0.6}:d=0.6[v]"
    )

    with tempfile.TemporaryDirectory() as tmp:
        overlay_path = Path(tmp) / "overlay.png"
        overlay_path.write_bytes(overlay_png)
        out_path = Path(tmp) / "clip.mp4"
        command = [
            binary, "-y",
            "-loop", "1", "-i", str(background),
            "-loop", "1", "-i", str(overlay_path),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-t", str(duration), "-r", str(FPS),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            "-movflags", "+faststart",
            str(out_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise PublishError("ffmpeg", f"video render failed: {stderr[-400:].decode(errors='replace')}")
        return out_path.read_bytes()


async def overlay_on_video(video: Path, overlay_png: bytes) -> bytes:
    """Composite the brand overlay onto an existing clip (e.g. AI-animated)."""
    binary = ffmpeg_path()
    if binary is None:
        raise ConfigurationError("ffmpeg is not installed — video rendering unavailable")

    filter_complex = (
        f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT}[bgv];"
        "[1:v]format=rgba,fade=t=in:st=0.9:d=1.1:alpha=1[ov];"
        "[bgv][ov]overlay=0:0:shortest=1,format=yuv420p[v]"
    )
    with tempfile.TemporaryDirectory() as tmp:
        overlay_path = Path(tmp) / "overlay.png"
        overlay_path.write_bytes(overlay_png)
        out_path = Path(tmp) / "clip.mp4"
        command = [
            binary, "-y",
            "-i", str(video),
            "-loop", "1", "-i", str(overlay_path),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-r", str(FPS),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            "-movflags", "+faststart",
            str(out_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise PublishError("ffmpeg", f"overlay failed: {stderr[-400:].decode(errors='replace')}")
        return out_path.read_bytes()


async def render_clip_to_storage(
    background: Path,
    brief: ClipBrief,
    colors: dict[str, str],
    logo: bytes | None = None,
    *,
    prefix: str = "clip",
    duration: int = DEFAULT_DURATION_SEC,
) -> StoredFile:
    overlay = build_overlay(brief, colors, logo)
    data = await render_clip(background, overlay, duration=duration)
    return get_storage().save_bytes(data, prefix=prefix, content_type="video/mp4")
