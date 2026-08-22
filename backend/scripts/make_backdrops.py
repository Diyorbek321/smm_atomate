"""Generate procedural brand backdrops — no image API, no per-asset cost.

The kinetic engine needs a library of backgrounds; a photo model is one way to
fill it, but geometry is a better fit for technical subjects (and always
available). Each generator draws thin brand-gold line art over charcoal with a
blurred depth layer, a vignette and film grain.

    python scripts/make_backdrops.py media/brand/photos [--prefix it]
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

W, H = 1080, 1920
INK = (20, 20, 20)
GOLD = (201, 162, 39)
IVORY = (245, 242, 234)


def _layer() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def _gold(alpha: int) -> tuple[int, int, int, int]:
    return (*GOLD, alpha)


def ui_wireframe(rng: random.Random) -> Image.Image:
    """Browser windows and cards — the frontend half of the story."""
    layer, draw = _layer()
    for index in range(3):
        x = 90 + index * 60
        y = 240 + index * 330
        w, h = 760 - index * 90, 470
        draw.rounded_rectangle([x, y, x + w, y + h], radius=26, outline=_gold(150 - index * 30),
                               width=3)
        draw.line([(x, y + 62), (x + w, y + 62)], fill=_gold(110 - index * 25), width=2)
        for dot in range(3):
            cx = x + 30 + dot * 26
            draw.ellipse([cx - 7, y + 24, cx + 7, y + 38], outline=_gold(130), width=2)
        for row in range(3):
            ry = y + 110 + row * 58
            draw.rounded_rectangle(
                [x + 34, ry, x + 34 + rng.randint(180, w - 80), ry + 22],
                radius=11, fill=_gold(38 - row * 8),
            )
        draw.rounded_rectangle(
            [x + 34, y + h - 96, x + 214, y + h - 40], radius=14, fill=_gold(70)
        )
    return layer


def server_stack(rng: random.Random) -> Image.Image:
    """Racks and database cylinders — the backend half."""
    layer, draw = _layer()
    x, w = 250, 580
    for index in range(5):
        y = 300 + index * 150
        draw.rounded_rectangle([x, y, x + w, y + 110], radius=16, outline=_gold(140), width=3)
        for slot in range(6):
            sx = x + 40 + slot * 42
            draw.rounded_rectangle([sx, y + 34, sx + 22, y + 76], radius=6, fill=_gold(45))
        for led in range(3):
            lx = x + w - 60 + led * 16
            draw.ellipse([lx, y + 48, lx + 9, y + 57], fill=_gold(rng.choice((90, 160, 220))))
    for index in range(3):                        # database cylinders
        cy = 1180 + index * 96
        draw.ellipse([x + 120, cy, x + 460, cy + 60], outline=_gold(150), width=3)
        draw.line([(x + 120, cy + 30), (x + 120, cy + 96)], fill=_gold(120), width=3)
        draw.line([(x + 460, cy + 30), (x + 460, cy + 96)], fill=_gold(120), width=3)
    return layer


def network(rng: random.Random) -> Image.Image:
    """Nodes and edges — data moving between client and server."""
    layer, draw = _layer()
    nodes = [(rng.randint(110, W - 110), rng.randint(280, H - 320)) for _ in range(16)]
    for i, (x0, y0) in enumerate(nodes):
        for x1, y1 in nodes[i + 1:]:
            if math.dist((x0, y0), (x1, y1)) < 430:
                draw.line([(x0, y0), (x1, y1)], fill=_gold(46), width=2)
    for x, y in nodes:
        radius = rng.choice((9, 13, 18))
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=_gold(190))
        draw.ellipse(
            [x - radius * 2.4, y - radius * 2.4, x + radius * 2.4, y + radius * 2.4],
            outline=_gold(60), width=2,
        )
    return layer


def code_rain(rng: random.Random) -> Image.Image:
    """Columns of glyph blocks falling — abstract code, never real text."""
    layer, draw = _layer()
    for column in range(14):
        x = 70 + column * 68
        length = rng.randint(6, 18)
        top = rng.randint(180, 900)
        for row in range(length):
            y = top + row * 46
            if y > H - 160:
                break
            alpha = int(150 * (1 - row / length)) + 20
            width = rng.choice((26, 34, 44))
            draw.rounded_rectangle([x, y, x + width, y + 16], radius=5, fill=_gold(alpha))
    return layer


def terminal(rng: random.Random) -> Image.Image:
    """A console window mid-session — the most literal 'developer' cue."""
    layer, draw = _layer()
    x, y, w, h = 110, 430, 860, 1020
    draw.rounded_rectangle([x, y, x + w, y + h], radius=28, outline=_gold(160), width=3)
    draw.line([(x, y + 70), (x + w, y + 70)], fill=_gold(120), width=2)
    for dot in range(3):
        cx = x + 36 + dot * 30
        draw.ellipse([cx - 8, y + 27, cx + 8, y + 43], outline=_gold(140), width=2)
    line_y = y + 120
    while line_y < y + h - 90:
        indent = rng.choice((0, 40, 80))
        draw.rounded_rectangle(
            [x + 44 + indent, line_y, x + 44 + indent + rng.randint(120, 520), line_y + 18],
            radius=6, fill=_gold(rng.randint(40, 120)),
        )
        line_y += 54
    draw.rectangle([x + 44, line_y, x + 74, line_y + 22], fill=_gold(200))     # cursor
    return layer


def grid_horizon(rng: random.Random) -> Image.Image:
    """Perspective grid — depth without a photograph."""
    layer, draw = _layer()
    horizon = 980
    for step in range(16):
        y = horizon + int((step ** 2) * 3.4)
        if y > H:
            break
        draw.line([(0, y), (W, y)], fill=_gold(max(20, 130 - step * 8)), width=2)
    for column in range(-10, 11):
        x = W // 2 + column * 130
        draw.line([(W // 2 + column * 26, horizon), (x, H)], fill=_gold(70), width=2)
    for _ in range(30):                            # stars above the horizon
        x, y = rng.randint(0, W), rng.randint(120, horizon - 60)
        size = rng.choice((3, 4, 6))
        draw.ellipse([x, y, x + size, y + size], fill=_gold(rng.randint(70, 190)))
    return layer


GENERATORS = {
    "ui": ui_wireframe,
    "server": server_stack,
    "network": network,
    "code": code_rain,
    "terminal": terminal,
    "grid": grid_horizon,
}


def compose(name: str, seed: int) -> Image.Image:
    """Blurred depth copy + sharp foreground + vignette + grain."""
    rng = random.Random(seed)
    art = GENERATORS[name](rng)

    base = Image.new("RGB", (W, H), INK)
    glow = Image.new("RGB", (W, H), (34, 30, 22))
    mask = Image.radial_gradient("L").resize((W, H)).point(lambda v: max(0, 220 - v))
    base.paste(glow, (0, 0), mask)

    # The kinetic engine tints backdrops with a 0.58-0.84 scrim, so line art
    # drawn at "correct" opacity disappears in the clip. Lift it here instead
    # of thickening every stroke in every generator.
    art.putalpha(art.getchannel("A").point(lambda v: min(255, int(v * 1.9))))

    depth = art.filter(ImageFilter.GaussianBlur(22))
    depth.putalpha(depth.getchannel("A").point(lambda v: int(v * 0.65)))
    base.paste(depth, (0, 0), depth)
    base.paste(art, (0, 0), art)

    vignette = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    ring = Image.new("L", (W // 4, H // 4), 0)
    ring_draw = ImageDraw.Draw(ring)
    for step in range(24):
        k = step / 24
        inset = int(-150 * (1 - k))
        ring_draw.ellipse(
            [inset, inset, W // 4 - inset, H // 4 - inset], outline=int(140 * (1 - k) ** 2), width=12
        )
    vignette.putalpha(ring.resize((W, H)).filter(ImageFilter.GaussianBlur(48)))
    base.paste(vignette, (0, 0), vignette)

    grain = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    grain.putalpha(Image.effect_noise((W // 2, H // 2), 30).resize((W, H))
                   .point(lambda v: min(20, abs(v - 128) // 4)))
    base.paste(grain, (0, 0), grain)
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="directory to write the backdrops into")
    parser.add_argument("--prefix", default="gen", help="filename prefix")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    args.target.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(GENERATORS, start=1):
        image = compose(name, args.seed + index * 31)
        path = args.target / f"{args.prefix}_{index:02d}_{name}.jpg"
        image.save(path, quality=88, optimize=True)
        print(f"{path}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
