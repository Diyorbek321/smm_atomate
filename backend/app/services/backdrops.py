"""Procedural brand backdrops — a visual library per client, drawn in code.

A photo model can fill this library too, but geometry never runs out of quota,
costs nothing and always lands in the client's own palette. Six motifs are
enough for a clip to never repeat a background twice in a row.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.core.logging import get_logger

log = get_logger(__name__)

W, H = 1080, 1920

DEFAULT_INK = (20, 20, 20)
DEFAULT_ACCENT = (201, 162, 39)


def _rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    value = (value or "").lstrip("#")
    if len(value) != 6:
        return fallback
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return fallback


def _layer() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def ui_wireframe(rng: random.Random, accent) -> Image.Image:
    """Browser windows and cards — screens, apps, anything digital."""
    layer, draw = _layer()

    def gold(alpha: int):
        return (*accent, alpha)

    for index in range(3):
        x, y = 90 + index * 60, 240 + index * 330
        w, h = 760 - index * 90, 470
        draw.rounded_rectangle([x, y, x + w, y + h], radius=26, outline=gold(150 - index * 30), width=3)
        draw.line([(x, y + 62), (x + w, y + 62)], fill=gold(110 - index * 25), width=2)
        for dot in range(3):
            cx = x + 30 + dot * 26
            draw.ellipse([cx - 7, y + 24, cx + 7, y + 38], outline=gold(130), width=2)
        for row in range(3):
            ry = y + 110 + row * 58
            draw.rounded_rectangle(
                [x + 34, ry, x + 34 + rng.randint(180, w - 80), ry + 22], radius=11,
                fill=gold(38 - row * 8),
            )
        draw.rounded_rectangle([x + 34, y + h - 96, x + 214, y + h - 40], radius=14, fill=gold(70))
    return layer


def server_stack(rng: random.Random, accent) -> Image.Image:
    """Racks and database cylinders — infrastructure, storage, systems."""
    layer, draw = _layer()

    def gold(alpha: int):
        return (*accent, alpha)

    x, w = 250, 580
    for index in range(5):
        y = 300 + index * 150
        draw.rounded_rectangle([x, y, x + w, y + 110], radius=16, outline=gold(140), width=3)
        for slot in range(6):
            sx = x + 40 + slot * 42
            draw.rounded_rectangle([sx, y + 34, sx + 22, y + 76], radius=6, fill=gold(45))
        for led in range(3):
            lx = x + w - 60 + led * 16
            draw.ellipse([lx, y + 48, lx + 9, y + 57], fill=gold(rng.choice((90, 160, 220))))
    for index in range(3):
        cy = 1180 + index * 96
        draw.ellipse([x + 120, cy, x + 460, cy + 60], outline=gold(150), width=3)
        draw.line([(x + 120, cy + 30), (x + 120, cy + 96)], fill=gold(120), width=3)
        draw.line([(x + 460, cy + 30), (x + 460, cy + 96)], fill=gold(120), width=3)
    return layer


def network(rng: random.Random, accent) -> Image.Image:
    """Nodes and edges — connection, community, reach."""
    layer, draw = _layer()

    def gold(alpha: int):
        return (*accent, alpha)

    nodes = [(rng.randint(110, W - 110), rng.randint(280, H - 320)) for _ in range(16)]
    for i, (x0, y0) in enumerate(nodes):
        for x1, y1 in nodes[i + 1:]:
            if math.dist((x0, y0), (x1, y1)) < 430:
                draw.line([(x0, y0), (x1, y1)], fill=gold(46), width=2)
    for x, y in nodes:
        radius = rng.choice((9, 13, 18))
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=gold(190))
        draw.ellipse(
            [x - radius * 2.4, y - radius * 2.4, x + radius * 2.4, y + radius * 2.4],
            outline=gold(60), width=2,
        )
    return layer


def code_rain(rng: random.Random, accent) -> Image.Image:
    """Columns of glyph blocks — abstract code, never real text."""
    layer, draw = _layer()
    for column in range(14):
        x = 70 + column * 68
        length, top = rng.randint(6, 18), rng.randint(180, 900)
        for row in range(length):
            y = top + row * 46
            if y > H - 160:
                break
            alpha = int(150 * (1 - row / length)) + 20
            draw.rounded_rectangle(
                [x, y, x + rng.choice((26, 34, 44)), y + 16], radius=5, fill=(*accent, alpha)
            )
    return layer


def terminal(rng: random.Random, accent) -> Image.Image:
    """A console mid-session — the most literal 'we build things' cue."""
    layer, draw = _layer()

    def gold(alpha: int):
        return (*accent, alpha)

    x, y, w, h = 110, 430, 860, 1020
    draw.rounded_rectangle([x, y, x + w, y + h], radius=28, outline=gold(160), width=3)
    draw.line([(x, y + 70), (x + w, y + 70)], fill=gold(120), width=2)
    for dot in range(3):
        cx = x + 36 + dot * 30
        draw.ellipse([cx - 8, y + 27, cx + 8, y + 43], outline=gold(140), width=2)
    line_y = y + 120
    while line_y < y + h - 90:
        indent = rng.choice((0, 40, 80))
        draw.rounded_rectangle(
            [x + 44 + indent, line_y, x + 44 + indent + rng.randint(120, 520), line_y + 18],
            radius=6, fill=gold(rng.randint(40, 120)),
        )
        line_y += 54
    draw.rectangle([x + 44, line_y, x + 74, line_y + 22], fill=gold(200))
    return layer


def grid_horizon(rng: random.Random, accent) -> Image.Image:
    """Perspective grid — depth and forward motion without a photograph."""
    layer, draw = _layer()

    def gold(alpha: int):
        return (*accent, alpha)

    horizon = 980
    for step in range(16):
        y = horizon + int((step ** 2) * 3.4)
        if y > H:
            break
        draw.line([(0, y), (W, y)], fill=gold(max(20, 130 - step * 8)), width=2)
    for column in range(-10, 11):
        draw.line(
            [(W // 2 + column * 26, horizon), (W // 2 + column * 130, H)], fill=gold(70), width=2
        )
    for _ in range(30):
        x, y = rng.randint(0, W), rng.randint(120, horizon - 60)
        size = rng.choice((3, 4, 6))
        draw.ellipse([x, y, x + size, y + size], fill=gold(rng.randint(70, 190)))
    return layer


GENERATORS = {
    "ui": ui_wireframe,
    "server": server_stack,
    "network": network,
    "code": code_rain,
    "terminal": terminal,
    "grid": grid_horizon,
}


def compose(name: str, seed: int, ink: tuple[int, int, int], accent: tuple[int, int, int]):
    """Blurred depth copy + sharp foreground + vignette + grain."""
    rng = random.Random(seed)
    art = GENERATORS[name](rng, accent)

    # Clips tint backdrops with a 0.58-0.84 scrim, so line art drawn at
    # "correct" opacity disappears. Lift it here rather than in every motif.
    art.putalpha(art.getchannel("A").point(lambda v: min(255, int(v * 1.9))))

    base = Image.new("RGB", (W, H), ink)
    glow = Image.new("RGB", (W, H), tuple(int(i + (a - i) * 0.12) for i, a in zip(ink, accent, strict=False)))
    base.paste(glow, (0, 0), Image.radial_gradient("L").resize((W, H)).point(lambda v: max(0, 220 - v)))

    depth = art.filter(ImageFilter.GaussianBlur(22))
    depth.putalpha(depth.getchannel("A").point(lambda v: int(v * 0.65)))
    base.paste(depth, (0, 0), depth)
    base.paste(art, (0, 0), art)

    ring = Image.new("L", (W // 4, H // 4), 0)
    ring_draw = ImageDraw.Draw(ring)
    for step in range(24):
        k = step / 24
        inset = int(-150 * (1 - k))
        ring_draw.ellipse(
            [inset, inset, W // 4 - inset, H // 4 - inset], outline=int(140 * (1 - k) ** 2), width=12
        )
    vignette = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    vignette.putalpha(ring.resize((W, H)).filter(ImageFilter.GaussianBlur(48)))
    base.paste(vignette, (0, 0), vignette)

    grain = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    grain.putalpha(
        Image.effect_noise((W // 2, H // 2), 30).resize((W, H)).point(lambda v: min(20, abs(v - 128) // 4))
    )
    base.paste(grain, (0, 0), grain)
    return base


def generate_library(
    target: Path, colors: dict[str, str] | None = None, *, prefix: str = "gen", seed: int = 7
) -> list[Path]:
    """Draw the whole set into `target`, in this client's brand colours."""
    palette = colors or {}
    ink = _rgb(palette.get("bg", ""), DEFAULT_INK)
    accent = _rgb(palette.get("accent", ""), DEFAULT_ACCENT)

    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, name in enumerate(GENERATORS, start=1):
        path = target / f"{prefix}_{index:02d}_{name}.jpg"
        compose(name, seed + index * 31, ink, accent).save(path, quality=88, optimize=True)
        written.append(path)
    log.info("backdrops_generated", target=str(target), count=len(written))
    return written
