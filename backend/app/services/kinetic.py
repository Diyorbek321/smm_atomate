"""Kinetic typography engine — agency-style vertical promos, no After Effects.

The reference genre: 10-20s vertical clips where one phrase = one scene, the
accent word lands in the brand colour, props bounce in with overshoot, the cut
is hidden by a colour wipe and every beat carries a whoosh or a pop.

Everything here is deterministic drawing: PIL renders each frame over a
generated brand backdrop (Ken Burns + scrim + vignette + grain), ffmpeg
assembles them, and the soundtrack is synthesised sample by sample with the
stdlib `wave` module. No external API, no per-clip cost.
"""

from __future__ import annotations

import array
import asyncio
import contextlib
import math
import random
import tempfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from app.core.config import settings
from app.core.exceptions import ConfigurationError, PublishError
from app.core.logging import get_logger
from app.services.encoding import audio_args, loudnorm_filter, video_args
from app.services.music import (
    Bed,
    bed_spec,
    channels_of,
    pan_gain,
    render_bed,
    snap_to_beat,
    write_wav,
)
from app.services.storage import StoredFile, get_storage
from app.services.video import ffmpeg_path

log = get_logger(__name__)

#: The whole layout is authored on this grid; RENDER_SCALE lifts it to the
#: delivery resolution so no coordinate ever has to be re-tuned by hand.
BASE_W, BASE_H = 720, 1280
RENDER_SCALE = max(0.5, min(3.0, float(settings.kinetic_scale)))
W, H = int(BASE_W * RENDER_SCALE), int(BASE_H * RENDER_SCALE)
FPS = 30
SAMPLE_RATE = 44100


def px(value: float) -> int:
    """Design units → device pixels."""
    return int(round(value * RENDER_SCALE))


#: Side of a square 3D prop render, in design units. The object itself covers
#: roughly the middle 72% of that square — the rest is the black backing the
#: radial mask fades out — so the layout reserves `PROP_RENDER_EXTENT`, not the
#: full side, or the text band below it collapses.
#: Frames a cut cross-blurs over. Five at 30 fps is ~0.17 s — long enough to
#: read as a move, short enough that no information is lost inside it.
WHIP_FRAMES = 5

PROP_RENDER_SIZE = 520
PROP_RENDER_EXTENT = 0.72

#: Nothing important is drawn outside this box — platform UI overlaps the rest.
SAFE_X, SAFE_TOP, SAFE_BOTTOM = px(56), px(168), px(1140)

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

#: Entry directions cycled across scenes so no two neighbours move alike.
DIRECTIONS = ("up", "left", "right", "down", "scale")
_OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left", "scale": "scale"}


# --------------------------------------------------------------------------- #
# Fonts, easing, colour
# --------------------------------------------------------------------------- #


def _mono(size: int, weight: int = 600) -> ImageFont.ImageFont:
    """Monospace face for code scenes — the fastest way to say 'software'."""
    for path in (_FONT_DIR / "JetBrainsMono.ttf",
                 Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")):
        try:
            font = ImageFont.truetype(str(path), px(size))
            with contextlib.suppress(OSError):
                font.set_variation_by_axes([weight])
            return font
        except OSError:
            continue
    return _font(size)


def _font(size: int, *, display: bool = False, weight: int = 700) -> ImageFont.ImageFont:
    candidates = ([_FONT_DIR / "Unbounded.ttf"] if display else [_FONT_DIR / "Manrope.ttf"]) + [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        try:
            font = ImageFont.truetype(str(path), px(size))
            with contextlib.suppress(OSError):
                font.set_variation_by_axes([weight])
            return font
        except OSError:
            continue
    return ImageFont.load_default()


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_out_expo(t: float) -> float:
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


def ease_out_back(t: float) -> float:
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _rgb(value: str, fallback: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    value = (value or "").lstrip("#")
    if len(value) != 6:
        return fallback
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return fallback


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return (
        int(a[0] + (b[0] - a[0]) * k),
        int(a[1] + (b[1] - a[1]) * k),
        int(a[2] + (b[2] - a[2]) * k),
    )


# --------------------------------------------------------------------------- #
# Scene model
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Scene:
    kind: str = "text"     # text | prop | stat | chapter | split | code | outro
    text: str = ""
    accent: str = ""
    sub: str = ""
    #: chapter → section number ("02"); stat → the figure ("350 000");
    #: split → the right-hand title
    value: str = ""
    #: split → one line per column; code → the lines typed into the window
    items: list[str] = field(default_factory=list)
    duration: float = 2.0


@dataclass(slots=True)
class KineticSpec:
    scenes: list[Scene]
    colors: dict[str, str]
    brand: str = ""
    phone: str = ""
    footer: str = ""
    logo: bytes | None = None
    prop_photos: list[Path] = field(default_factory=list)
    #: 3D object renders on a black backing — screen-blended into the scene
    #: rather than framed like a photo. Preferred over `prop_photos` when both
    #: are available, because a rendered object carries a scene and a
    #: stock photograph decorates one.
    prop_renders: list[Path] = field(default_factory=list)
    #: A licensed track to lay under the clip; without one the engine
    #: synthesises its own tempo-locked bed.
    music: Path | None = None
    bpm: int = 96
    energy: str = "calm"
    #: What the clip is about. Only the bed reads it — it chooses the
    #: progression, the opening bar and the shaker, so two clips for the same
    #: business are different pieces rather than the same one twice. The
    #: tempo is `bpm`, set alongside it, because cuts snap to that number.
    subject: str = ""


# --------------------------------------------------------------------------- #
# Soundtrack — synthesised, then mixed into a single track
# --------------------------------------------------------------------------- #


def _env(i: int, n: int, attack: float = 0.08) -> float:
    """Attack/decay envelope in [0,1]."""
    pos = i / max(1, n)
    if pos < attack:
        return pos / attack
    return (1 - (pos - attack) / (1 - attack)) ** 1.6


def _coeff(hz: float) -> float:
    """One-pole coefficient for a cutoff in Hz."""
    return 1.0 - math.exp(-2 * math.pi * hz / SAMPLE_RATE)


def band_noise(n: int, rng: random.Random, low_hz: float, high_hz: float) -> list[float]:
    """Band-limited noise.

    Raw ``uniform(-1, 1)`` is white, and white noise is what makes a cue read
    as static rather than as air. Every noise-based cue goes through here so
    its energy sits in a band we chose instead of across the whole spectrum.
    """
    a_hi, a_lo = _coeff(high_hz), _coeff(low_hz)
    hi1 = hi2 = lo1 = lo2 = 0.0
    out: list[float] = []
    for _ in range(n):
        white = rng.uniform(-1, 1)
        hi1 += (white - hi1) * a_hi                  # cascaded: 12 dB/oct, not 6.
        hi2 += (hi1 - hi2) * a_hi                    # One pole leaks far too
        lo1 += (white - lo1) * a_lo                  # much above the corner to
        lo2 += (lo1 - lo2) * a_lo                    # call the result banded.
        out.append((hi2 - lo2) * 2.6)                # make up the lost level
    return out


def _sfx_whoosh(duration: float = 0.5) -> list[float]:
    """Air sweeping dull → open → dull: the transition sound.

    The sweep tops out at ~3 kHz. It used to add a complementary highpass tail
    on top of the sweep, which put broadband energy in the sibilance band on
    every single cut — the harshest thing in the mix.
    """
    rng = random.Random(11)
    n = int(duration * SAMPLE_RATE)
    out: list[float] = []
    one = two = 0.0
    for i in range(n):
        pos = i / n
        white = rng.uniform(-1, 1)
        a = _coeff(220) + _coeff(2100) * math.sin(math.pi * pos) ** 1.5
        one += (white - one) * a
        two += (one - two) * a                       # second pole: 12 dB/oct
        out.append(two * _env(i, n, 0.35) * 0.85)
    return out


def _sfx_pop() -> list[float]:
    """Short pitched click for a word or a prop landing."""
    n = int(0.16 * SAMPLE_RATE)
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 1150 * math.exp(-26 * t) + 190
        out.append(math.sin(2 * math.pi * freq * t) * math.exp(-24 * t) * 0.8)
    return out


def _sfx_tick() -> list[float]:
    """Tiny click under each word — the texture that sells the edit.

    Pitched down from 2.6 kHz and its white-noise half replaced with a narrow
    band: at one tick per word these stack up, and stacked white noise is
    fatigue.
    """
    rng = random.Random(3)
    n = int(0.05 * SAMPLE_RATE)
    noise = band_noise(n, rng, 900, 3400)
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        out.append(
            (math.sin(2 * math.pi * 1750 * t) * 0.62 + noise[i] * 1.1)
            * math.exp(-90 * t) * 0.27
        )
    return out


def _sfx_riser(duration: float = 1.0) -> list[float]:
    """Rising tone that pulls the viewer into the outro."""
    n = int(duration * SAMPLE_RATE)
    out = []
    phase = 0.0
    for i in range(n):
        pos = i / n
        phase += 2 * math.pi * (180 + 900 * pos ** 2) / SAMPLE_RATE
        out.append(math.sin(phase) * (pos ** 2) * 0.42)
    return out


def _sfx_impact() -> list[float]:
    """Sub-bass hit — the logo landing.

    The broadband crack this used to open with pushed the cue past full scale
    (peak 1.22) and gave every chapter marker a click. A short band-limited
    thump gives the same sense of arrival without either problem.
    """
    rng = random.Random(5)
    n = int(0.90 * SAMPLE_RATE)
    thump = band_noise(n, rng, 120, 700)
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        sub = math.sin(2 * math.pi * (88 * math.exp(-3 * t) + 40) * t) * math.exp(-3.8 * t)
        out.append((sub * 0.92 + thump[i] * math.exp(-26 * t) * 0.30) * 0.82)
    return out


def sfx_library() -> dict[str, list[float]]:
    return {
        "whoosh": _sfx_whoosh(),
        "pop": _sfx_pop(),
        "tick": _sfx_tick(),
        "riser": _sfx_riser(),
        "impact": _sfx_impact(),
    }


#: Where each cue sits in the stereo field. Transitions travel across it —
#: a whoosh that moves is heard as the edit moving — while anything that
#: lands on the cut itself stays centred with the kick.
CUE_PAN = {"whoosh": 0.55, "riser": 0.30}


def mix_soundtrack(
    cues: list[tuple[str, float, float]],
    duration: float,
    path: Path,
    bed: Bed | array.array | None = None,
) -> Path:
    """Sum every cue (and the music bed) into one stereo WAV — one ffmpeg input."""
    library = sfx_library()
    total = int((duration + 0.6) * SAMPLE_RATE)
    left = array.array("d", bytes(8 * total))
    right = array.array("d", bytes(8 * total))

    channels = channels_of(bed)
    if channels is not None:
        bed_l, bed_r = channels
        for index in range(min(total, len(bed_l))):
            left[index] += bed_l[index]
            right[index] += bed_r[index]

    for order, (name, at, gain) in enumerate(cues):
        sound = library.get(name)
        if not sound:
            continue
        # Successive whooshes alternate sides, so a six-scene edit sweeps back
        # and forth rather than firing the same sound six times.
        swing = CUE_PAN.get(name, 0.0) * (1 if order % 2 else -1)
        gain_l = gain * pan_gain(-swing)
        gain_r = gain * pan_gain(swing)
        start = int(max(0.0, at) * SAMPLE_RATE)
        for offset, sample in enumerate(sound):
            index = start + offset
            if index >= total:
                break
            left[index] += sample * gain_l
            right[index] += sample * gain_r

    return write_wav(Bed(soften(left), soften(right)), path)


def soften(samples: array.array) -> array.array:
    """Master shaping: shelve the top end down, then limit only the peaks.

    Two jobs. The shelf tames the top end, where synthesised cues pile up and
    where phone speakers are harshest. The limiter leaves anything under 0.82
    untouched, so it shapes transients instead of adding the saturation
    harmonics a plain tanh() puts on the whole signal.

    The shelf used to take 4.5 dB off everything above 4 kHz. Against a bed
    whose sources are near-pure sines that is most of the harmonic content it
    has, and the result measured — and sounded — dull. 2 dB still catches the
    harshness without removing the air.
    """
    a = _coeff(4000)
    low = 0.0
    for i, value in enumerate(samples):
        low += (value - low) * a
        shaped = low + (value - low) * 0.79          # -2.0 dB above 4 kHz
        magnitude = abs(shaped)
        if magnitude > 0.82:
            shaped = math.copysign(
                0.82 + 0.18 * math.tanh((magnitude - 0.82) / 0.18), shaped
            )
        samples[i] = shaped
    return samples


# --------------------------------------------------------------------------- #
# Reusable overlays (built once per process)
# --------------------------------------------------------------------------- #

_vignette_cache: Image.Image | None = None
_grain_cache: list[Image.Image] = []
_mask_cache: dict[int, Image.Image] = {}


def _vignette_overlay() -> Image.Image:
    global _vignette_cache
    if _vignette_cache is None:
        mask = Image.new("L", (W // 4, H // 4), 0)
        draw = ImageDraw.Draw(mask)
        for step in range(28):
            k = step / 28
            inset = int(-160 * (1 - k))
            draw.ellipse(
                [inset, inset, W // 4 - inset, H // 4 - inset],
                outline=int(150 * (1 - k) ** 2),
                width=max(2, px(14) // 4),
            )
        blurred = mask.resize((W, H)).filter(ImageFilter.GaussianBlur(px(50)))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        layer.putalpha(blurred)
        _vignette_cache = layer
    return _vignette_cache


def _grain_overlays() -> list[Image.Image]:
    if not _grain_cache:
        for _ in range(3):
            noise = Image.effect_noise((W // 2, H // 2), 34).resize((W, H))
            layer = Image.new("RGBA", (W, H), (255, 255, 255, 0))
            layer.putalpha(noise.point(lambda v: min(24, abs(v - 128) // 3)))
            _grain_cache.append(layer)
    return _grain_cache


# --------------------------------------------------------------------------- #
# Backdrop — generated brand imagery, never a flat colour
# --------------------------------------------------------------------------- #


class _Backdrop:
    """Ken Burns over a generated brand image, tinted for text contrast."""

    def __init__(
        self,
        photo: Path | None,
        treatment: str,
        ink: tuple[int, int, int],
        wash: tuple[int, int, int],
        seed: int,
    ) -> None:
        self.treatment = treatment
        rng = random.Random(seed)
        self.pan = rng.choice(("lr", "rl", "tb", "bt"))
        self.alpha = {"dark": 0.58, "light": 0.84, "accent": 0.76}.get(treatment, 0.6)
        self.scrim = Image.new("RGB", (W, H), wash)

        source: Image.Image | None = None
        if photo is not None:
            try:
                image = Image.open(photo).convert("RGB").resize((int(W * 1.34), int(H * 1.34)))
                if treatment != "dark":
                    image = image.filter(ImageFilter.GaussianBlur(px(14)))
                source = image
            except OSError:
                source = None
        if source is None:                       # no library yet — soft gradient stand-in
            base = Image.new("RGB", (W, H), wash)
            glow = Image.new("RGB", (W, H), _mix(wash, ink, 0.45))
            mask = Image.radial_gradient("L").resize((W, H)).point(lambda v: 255 - v)
            base.paste(glow, (0, 0), mask)
            source = base.resize((int(W * 1.34), int(H * 1.34)))

        # Blending a flat colour is pointwise, so tinting the source once is
        # identical to tinting every cropped frame — and 30x cheaper.
        self.source = Image.blend(source, Image.new("RGB", source.size, wash), self.alpha)
        self._cache: tuple[int, Image.Image] | None = None

    def frame(self, t: float, bucket: int = 0) -> Image.Image:
        """Composited backdrop for this moment.

        `bucket` groups neighbouring frames: the camera move is slow enough that
        refreshing it every other frame is invisible and halves the cost of the
        most expensive operation in the renderer.
        """
        if self._cache is not None and self._cache[0] == bucket:
            return self._cache[1].copy()

        src = self.source
        sw, sh = src.size
        zoom = 1.0 - 0.075 * t                   # slow push-in
        cw, ch = min(int(W * 1.2 * zoom), sw), min(int(H * 1.2 * zoom), sh)
        span_x, span_y = sw - cw, sh - ch
        if self.pan == "lr":
            x, y = int(span_x * t), span_y // 2
        elif self.pan == "rl":
            x, y = int(span_x * (1 - t)), span_y // 2
        elif self.pan == "tb":
            x, y = span_x // 2, int(span_y * t)
        else:
            x, y = span_x // 2, int(span_y * (1 - t))

        canvas = src.crop((x, y, x + cw, y + ch)).resize((W, H), Image.BILINEAR)
        vignette = _vignette_overlay()
        canvas.paste(vignette, (0, 0), vignette)
        grains = _grain_overlays()
        grain = grains[bucket % len(grains)]
        canvas.paste(grain, (0, 0), grain)
        self._cache = (bucket, canvas)
        return canvas.copy()


# --------------------------------------------------------------------------- #
# Word tiles
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _Tile:
    image: Image.Image
    cx: int
    cy: int
    start: float
    direction: str
    marker: tuple[int, int, int, int] | None = None     # accent highlight bar
    underline: tuple[int, int, int, int] | None = None  # accent underline sweep
    reveal: bool = False                                # typewriter-style wipe-in


def count_up(value: str, progress: float) -> str:
    """Animate the digits inside a figure: 350 000 counts up, "10+" keeps its sign.

    Anything without digits is returned untouched, so a stat can hold a word.
    """
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits or progress >= 1:
        return value
    target = int(digits)
    current = int(target * clamp01(progress))
    grouped = f"{current:,}".replace(",", " ")
    head, tail = value.split(digits[0], 1)[0], value.rsplit(digits[-1], 1)[-1]
    return f"{head}{grouped}{tail}"


def reading_time(scene: Scene) -> float:
    """Seconds this scene needs before a viewer can finish reading it.

    The words assemble one by one, so a phrase is only whole for the tail of
    its scene — the runtime has to pay for both the build and the hold.
    """
    if scene.kind == "code":
        lines = len([line for line in scene.items if line.strip()]) or 1
        return round(min(7.0, 1.9 + 0.8 * lines), 2)
    if scene.kind == "split":
        words = sum(len(item.split()) for item in scene.items[:2])
        return round(min(7.0, 3.0 + 0.32 * words), 2)
    if scene.kind == "stat":
        return 3.0
    if scene.kind == "chapter":
        return 2.2
    if scene.kind == "outro":
        return 3.2

    seconds = 1.6 + 0.36 * len(scene.text.split())
    if scene.sub:
        seconds += 0.9
    return round(min(6.5, max(2.4, seconds)), 2)


def _wrap_plain(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: float
) -> list[str]:
    """Word-wrap a plain string — used by the column and caption layouts."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _norm(word: str) -> str:
    """Fold punctuation and the four apostrophe variants Uzbek text arrives in."""
    cleaned = word.strip(".,!?:;»«\"()").lower()
    for char in ("ʻ", "ʼ", "‘", "’", "`"):
        cleaned = cleaned.replace(char, "'")
    return cleaned


def resolve_accent(words: list[str], accent: str) -> int:
    """Index of the word to highlight — never -1 when a phrase has substance.

    The model is asked for an exact word but often returns a stem ("bilim" for
    "bilimlar") or something absent, so match loosely and fall back to the
    longest word: every scene must have one word that lands in brand colour.
    """
    if not words:
        return -1
    key = _norm(accent)
    normalised = [_norm(word) for word in words]
    if key:
        if key in normalised:
            return normalised.index(key)
        for index, word in enumerate(normalised):
            if len(key) >= 4 and (word.startswith(key) or key.startswith(word)):
                return index
    # Ties go to the later word: Uzbek puts the payload at the end of the phrase.
    longest = max(range(len(normalised)), key=lambda i: (len(normalised[i]), i))
    return longest if len(normalised[longest]) >= 3 else -1


def _wrap_words(
    words: list[str], accent_index: int, size: int, box_w: int
) -> tuple[list[list[tuple[str, bool, ImageFont.ImageFont, int]]], int]:
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    lines: list[list[tuple[str, bool, ImageFont.ImageFont, int]]] = [[]]
    widths = [0]
    longest = 0
    for position, word in enumerate(words):
        is_accent = position == accent_index
        font = _font(
            int(size * (1.08 if is_accent else 1.0)), display=True,
            weight=900 if is_accent else 700,
        )
        width = int(probe.textlength(word, font=font)) + px(size * 0.24)
        if widths[-1] + width > box_w and lines[-1]:
            lines.append([])
            widths.append(0)
        lines[-1].append((word, is_accent, font, width))
        widths[-1] += width
        longest = max(longest, widths[-1])
    return lines, longest


# --------------------------------------------------------------------------- #
# Scene renderer
# --------------------------------------------------------------------------- #


class _SceneRenderer:
    """Pre-computes tiles/props/backdrop once, then draws any t in [0,1]."""

    def __init__(self, scene: Scene, spec: KineticSpec, index: int) -> None:
        self.scene = scene
        self.spec = spec
        self.index = index
        self.seed = index * 977 + 13
        rng = random.Random(self.seed)

        ink = _rgb(spec.colors.get("bg", "#141414"), (20, 20, 20))
        ivory = _rgb(spec.colors.get("text", "#F5F2EA"), (245, 242, 234))
        gold = _rgb(spec.colors.get("accent", "#C9A227"), (201, 162, 39))
        self.ink, self.ivory, self.gold = ink, ivory, gold

        # Treatment rotation keeps neighbouring scenes visually distinct.
        treatments = ("dark", "light", "dark", "accent")
        # Code belongs on a dark screen — a terminal on a gold wash reads wrong
        # to anyone who has ever opened one.
        forced_dark = scene.kind in ("outro", "code")
        self.treatment = "dark" if forced_dark else treatments[index % len(treatments)]
        if self.treatment == "light":
            self.fg, self.accent_color, self.wash = ink, gold, ivory
        elif self.treatment == "accent":
            self.fg, self.accent_color, self.wash = ink, ivory, gold
        else:
            self.fg, self.accent_color, self.wash = ivory, gold, ink

        photo = None
        if spec.prop_photos:
            photo = spec.prop_photos[(index * 3 + 1) % len(spec.prop_photos)]
        self.photo_path = photo
        self.backdrop = _Backdrop(photo, self.treatment, ink, self.wash, self.seed)

        self.direction = DIRECTIONS[index % len(DIRECTIONS)]
        self.wipe_from = rng.choice(("left", "right", "top", "bottom"))
        # How this scene arrives. A colour wipe covers the whole frame in flat
        # accent for two frames — a hard brand hit that suits a section marker
        # and reads as a strobe anywhere else, so everything else cross-blurs
        # out of the scene before it. The opening scene arrives on its own.
        self.transition = (
            "none" if index == 0 else "wipe" if scene.kind == "chapter" else "whip"
        )
        # Technique budget: at most one special move per scene, and never two
        # scenes in a row — restraint is what separates an edit from a demo reel.
        self.reveal_scene = scene.kind == "text" and index % 4 == 3
        self.tiles: list[_Tile] = []
        self.word_beats: list[float] = []
        self.prop: Image.Image | None = None
        self.prop_blend = "normal"
        self.prop_extent = 0
        self.prop_center = (W // 2, px(470))
        self.sub_y = SAFE_BOTTOM - px(120)
        # Timings are authored in seconds and normalised against the scene, so
        # a longer scene holds its text longer instead of animating slower.
        self.entry_n = self._at(0.30)
        self.settle_n = self._at(1.30)
        self.sub_start = self._at(1.20)
        self._layout()

    def _at(self, seconds: float) -> float:
        """Where an absolute offset falls inside this scene's 0..1 timeline."""
        return clamp01(seconds / max(0.4, self.scene.duration))

    # -- layout ---------------------------------------------------------- #
    def _layout(self) -> None:
        scene = self.scene
        if scene.kind in ("outro", "chapter", "stat", "split", "code"):
            return                                # these draw themselves, no tiles

        if scene.kind == "prop":
            # A rendered object wins over a stock photo: it is brand-coloured,
            # it has depth, and it composites into the scene instead of sitting
            # in a medallion on top of it.
            self.prop = self._prop_render()
            if self.prop is not None:
                self.prop_blend = "screen" if self.treatment == "dark" else "normal"
                self.prop_extent = int(self.prop.height * PROP_RENDER_EXTENT)
            elif self.spec.prop_photos:
                self.prop = self._prop_image()
                self.prop_extent = self.prop.height if self.prop else 0
        if self.prop is not None:
            prop_h = self.prop_extent
            self.prop_center = (W // 2, SAFE_TOP + px(40) + prop_h // 2)
            box_top = self.prop_center[1] + prop_h // 2 + px(54)
            box_bottom = self.sub_y - px(72 if scene.sub else 24)
        else:
            box_top = SAFE_TOP + px(40)
            box_bottom = self.sub_y - px(84 if scene.sub else 24)

        box_h = max(px(180), box_bottom - box_top)
        box_w = W - (SAFE_X + px(14)) * 2            # keep glyphs clear of the edge
        words = scene.text.split()
        if not words:
            return

        accent_index = resolve_accent(words, scene.accent)
        size, lines, line_h = 92, [], 0
        for size in range(92, 40, -6):
            lines, longest = _wrap_words(words, accent_index, size, box_w)
            line_h = px(size * 1.26)
            if line_h * len(lines) <= box_h and longest <= box_w:
                break

        total_h = line_h * len(lines)
        top = box_top + (box_h - total_h) // 2
        seen, total_words = 0, max(1, len(words))

        # Assemble the phrase inside the first 60% of the scene whatever its
        # length; the rest of the time the sentence simply stands there to read.
        stagger = 0.095
        if total_words > 1:
            budget = self.scene.duration * 0.60 - 0.40
            stagger = max(0.035, min(stagger, budget / (total_words - 1)))
        self.sub_start = self._at(0.10 + (total_words - 1) * stagger + 0.45)
        for row, line in enumerate(lines):
            row_w = sum(item[3] for item in line)
            x = (W - row_w) // 2
            for word, is_accent, font, width in line:
                pad = px(size * 0.36)
                tile = Image.new("RGBA", (width + pad * 2, line_h + pad * 2), (0, 0, 0, 0))
                draw = ImageDraw.Draw(tile)
                # The highlighter bar is brand gold, so the word on top of it must
                # be ink — gold on gold is the one combination that disappears.
                use_marker = is_accent and self.treatment == "light"
                if use_marker:
                    colour = self.ink
                else:
                    colour = self.accent_color if is_accent else self.fg
                stroke = 3 if self.treatment == "dark" else 0
                draw.text(
                    (pad, pad + px(size * 0.06)), word, font=font, fill=(*colour, 255),
                    stroke_width=px(stroke),
                    stroke_fill=(*_mix(self.wash, (0, 0, 0), 0.4), 200),
                )
                marker = underline = None
                if use_marker:
                    # Highlighter bar behind the accent word (reference #2 move).
                    # Only on the ivory scene — on gold it would vanish into the wash.
                    marker = (
                        x, top + row * line_h + int(line_h * 0.60),
                        x + width, top + row * line_h + int(line_h * 0.92),
                    )
                elif is_accent:
                    # Dark scenes get a sweeping underline instead — same emphasis,
                    # readable over a photograph.
                    baseline = top + row * line_h + int(line_h * 0.96)
                    underline = (x + px(6), baseline, x + width - px(6), baseline + px(8))
                start = self._at(0.10 + seen * stagger)
                self.word_beats.append(start)
                # Words alternate between the scene direction and its opposite so
                # the line assembles from both sides instead of marching one way.
                direction = self.direction if seen % 2 == 0 else _OPPOSITE[self.direction]
                self.tiles.append(
                    _Tile(
                        image=tile,
                        cx=x + width // 2,
                        cy=top + row * line_h + line_h // 2,
                        start=start,
                        direction="scale" if is_accent else direction,
                        marker=marker,
                        underline=underline,
                        reveal=self.reveal_scene and not is_accent,
                    )
                )
                x += width
                seen += 1

    @staticmethod
    def _crush(image: Image.Image) -> Image.Image:
        """Push the near-black backing to true black.

        A render arrives with a faint floor gradient around the object. Under a
        screen blend anything above zero lightens the scene, and that gradient
        is what shows the prop's bounding box as a lighter rectangle.
        """
        lut = []
        for value in range(256):
            level = (value / 255) * 1.06
            level = (level - 0.5) * 1.30 + 0.5
            lut.append(max(0, min(255, round(level * 255))))
        return image.point(lut * 3)

    @staticmethod
    def _radial_mask(size: int) -> Image.Image:
        """Soft circular falloff, so no straight edge of the source survives."""
        cached = _mask_cache.get(size)
        if cached is not None:
            return cached
        mask = Image.new("L", (size, size), 0)
        # Inset, and blurred by less than the inset leaves to the corner: a
        # full-square ellipse blurred hard enough to feather still carries a
        # tail into the corners, which is the source's own bounding box
        # bleeding back into the scene.
        inset = int(size * 0.04)
        ImageDraw.Draw(mask).ellipse([inset, inset, size - 1 - inset, size - 1 - inset], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(size * 0.07))
        _mask_cache[size] = mask
        return mask

    def _prop_render(self) -> Image.Image | None:
        """A 3D object prepared for compositing on this scene's ground.

        The alpha baked in here decides how the object meets the background:

        * on a dark ground, a plain radial falloff — the draw step screens the
          object on, so its glow spills into the scene the way it would if the
          object were really lit there;
        * on a light or accent ground, the object's own luminance — screen is a
          no-op against near-white, so a chrome render simply disappears. Using
          luminance as the alpha keeps it an object rather than a wash.
        """
        renders = self.spec.prop_renders
        if not renders:
            return None
        pick = renders[(self.index * 5 + 2) % len(renders)]
        try:
            image = Image.open(pick).convert("RGB")
        except OSError:
            return None
        size = px(PROP_RENDER_SIZE)
        image = self._crush(image.resize((size, size)))
        mask = self._radial_mask(size)
        if self.treatment != "dark":
            mask = ImageChops.multiply(mask, image.convert("L"))
        out = image.convert("RGBA")
        out.putalpha(mask)
        return out

    def _prop_image(self) -> Image.Image | None:
        photos = self.spec.prop_photos
        if not photos:
            return None
        pick = photos[(self.index * 5 + 2) % len(photos)]
        try:
            photo = Image.open(pick).convert("RGB")
        except OSError:
            return None
        size, ring = px(340), px(13)
        photo = photo.resize((size, size))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
        framed = Image.new("RGBA", (size + ring * 2, size + ring * 2), (0, 0, 0, 0))
        ImageDraw.Draw(framed).ellipse(
            [0, 0, size + ring * 2 - 1, size + ring * 2 - 1], fill=(*self.accent_color, 255)
        )
        framed.paste(photo, (ring, ring), mask)
        return framed

    # -- drawing --------------------------------------------------------- #
    def frame(self, t: float, frame_index: int = 0) -> Image.Image:
        canvas = self.backdrop.frame(t, frame_index // 2)
        draw = ImageDraw.Draw(canvas, "RGBA")
        self._decor(draw, t)

        if self.scene.kind == "outro":
            self._outro(canvas, draw, t)
        elif self.scene.kind == "chapter":
            self._chapter(draw, t)
        elif self.scene.kind == "stat":
            self._stat(draw, t)
            self._sub_layer(draw, t)
        elif self.scene.kind == "split":
            self._split(draw, t)
            self._sub_layer(draw, t)
        elif self.scene.kind == "code":
            self._code(draw, t)
        else:
            self._prop_layer(canvas, t)
            self._text_layer(canvas, draw, t)
            self._sub_layer(draw, t)

        self._chrome(canvas, draw)
        self._wipe(draw, t)
        return canvas

    def _wipe(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        """Two-tone block swiping off the frame — hides the cut, lands the beat."""
        if self.transition != "wipe":
            return
        progress = clamp01(t / 0.16)
        if progress >= 1:
            return
        lead = ease_out_expo(progress)
        trail = ease_out_expo(clamp01((t - 0.05) / 0.16))
        first = (*self.accent_color, 255) if self.treatment != "accent" else (*self.ink, 255)
        second = (*self.ink, 255) if self.treatment != "dark" else (*self.ivory, 255)
        for travel, colour in ((trail, second), (lead, first)):
            if travel >= 1:
                continue
            if self.wipe_from == "left":
                draw.rectangle([-W + int(W * travel) - px(6), 0, int(W * travel), H], fill=colour)
            elif self.wipe_from == "right":
                draw.rectangle([W - int(W * travel), 0, 2 * W - int(W * travel), H], fill=colour)
            elif self.wipe_from == "top":
                draw.rectangle([0, -H + int(H * travel) - px(6), W, int(H * travel)], fill=colour)
            else:
                draw.rectangle([0, H - int(H * travel), W, 2 * H - int(H * travel)], fill=colour)

    def _decor(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        rng = random.Random(self.seed)
        accent = self.accent_color
        for _ in range(6):                        # drifting, pulsing sparkles
            x0, y0 = rng.randint(px(70), W - px(70)), rng.randint(SAFE_TOP, SAFE_BOTTOM)
            phase = rng.random()
            drift = math.sin((t + phase) * math.pi * 2) * px(14)
            size = px(9) + px(8) * math.sin((t * 2.2 + phase) * math.pi * 2) ** 2
            x, y = x0 + drift, y0 - drift * 0.6
            colour = accent if rng.random() > 0.35 else self.fg
            draw.polygon(
                [(x, y - size), (x + size * .28, y - size * .28), (x + size, y),
                 (x + size * .28, y + size * .28), (x, y + size), (x - size * .28, y + size * .28),
                 (x - size, y), (x - size * .28, y - size * .28)],
                fill=(*colour, 215),
            )
        if self.index % 2 == 0:                   # sweeping arc, revealed over time
            sweep = ease_out_cubic(clamp01((t - 0.05) / 0.7))
            draw.arc(
                [-px(160), px(300), W + px(160), H - px(180)], start=200,
                end=200 + int(150 * sweep), fill=(*accent, 150), width=px(7),
            )
        else:                                     # chevrons marching across
            shift = int((t * px(90)) % px(90))
            for i in range(-1, 9):
                x = i * px(90) + shift
                draw.line(
                    [(x, SAFE_BOTTOM - px(40)), (x + px(26), SAFE_BOTTOM - px(20)),
                     (x, SAFE_BOTTOM)], fill=(*accent, 95), width=px(5),
                )

    def _prop_layer(self, canvas: Image.Image, t: float) -> None:
        if self.prop is None:
            return
        progress = clamp01((t - 0.06) / 0.40)
        if progress <= 0:
            return
        scale = max(0.05, ease_out_back(progress))
        size = (max(1, int(self.prop.width * scale)), max(1, int(self.prop.height * scale)))
        scaled = self.prop.resize(size)
        cx, cy = self.prop_center
        # A prop that holds perfectly still for two seconds reads as a sticker.
        # A slow drift on its own axis is what gives the frame depth.
        cx += int(math.cos(t * 2.0 + self.index) * px(11))
        cy += int(math.sin(t * 2.7 + self.index) * px(15))
        left, top = cx - size[0] // 2, cy - size[1] // 2

        if self.prop_blend != "screen":
            canvas.paste(scaled, (left, top), scaled)
            return

        box = (left, top, left + size[0], top + size[1])
        region = canvas.crop(box).convert("RGB")
        lit = ImageChops.screen(region, scaled.convert("RGB"))
        region.paste(lit, (0, 0), scaled.getchannel("A"))
        canvas.paste(region, box)

    def _text_layer(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, t: float) -> None:
        entry = max(0.02, self.entry_n)
        for tile in self.tiles:
            progress = clamp01((t - tile.start) / entry)
            if progress <= 0:
                continue
            slide = ease_out_expo(progress)
            alpha = ease_out_cubic(min(1.0, progress * 1.5))
            dx = dy = 0
            scale = 1.0
            if tile.direction == "left":
                dx = px(-190 * (1 - slide))
            elif tile.direction == "right":
                dx = px(190 * (1 - slide))
            elif tile.direction == "up":
                dy = px(120 * (1 - slide))
            elif tile.direction == "down":
                dy = px(-120 * (1 - slide))
            else:
                scale = 0.55 + 0.45 * ease_out_back(progress)

            # After landing the word keeps drifting a few pixels the way it came
            # from — the difference between "animated once" and "alive".
            settle = clamp01((t - tile.start - entry) / max(0.02, self.settle_n))
            if settle > 0:
                if tile.direction == "left":
                    dx += px(7 * settle)
                elif tile.direction == "right":
                    dx -= px(7 * settle)
                elif tile.direction == "up":
                    dy -= px(5 * settle)
                elif tile.direction == "down":
                    dy += px(5 * settle)

            if tile.marker is not None:
                grow = ease_out_expo(clamp01((t - tile.start + entry * 0.2) / (entry * 1.2)))
                x0, y0, x1, y1 = tile.marker
                draw.rounded_rectangle(
                    [x0 + dx, y0 + dy, x0 + dx + int((x1 - x0) * grow), y1 + dy],
                    radius=px(6), fill=(*self.gold, 200),
                )
            if tile.underline is not None:
                grow = ease_out_expo(clamp01((t - tile.start - entry * 0.3) / (entry * 1.3)))
                if grow > 0:
                    x0, y0, x1, y1 = tile.underline
                    draw.rounded_rectangle(
                        [x0 + dx, y0 + dy, x0 + dx + int((x1 - x0) * grow), y1 + dy],
                        radius=px(4), fill=(*self.accent_color, 230),
                    )

            image = tile.image
            if scale != 1.0:
                image = image.resize(
                    (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                )
            if tile.reveal:
                # Typewriter wipe: the word is uncovered left to right in place.
                visible = max(1, int(image.width * ease_out_expo(progress)))
                image = image.crop((0, 0, visible, image.height))
                dx = dy = 0
            if alpha < 1:
                faded = image.copy()
                faded.putalpha(faded.getchannel("A").point(lambda v, a=alpha: int(v * a)))
                image = faded

            left = tile.cx - tile.image.width // 2 + dx
            top = tile.cy - image.height // 2 + dy
            if tile.reveal:
                canvas.paste(image, (left, top), image)
                continue

            # Motion trail: one fading ghost behind a word that is really moving.
            # (Two ghosts looked no better and cost 40% of the frame budget.)
            if progress < 0.5 and abs(dx) + abs(dy) > px(26):
                ghost = image.copy()
                ghost.putalpha(ghost.getchannel("A").point(lambda v: int(v * 0.28)))
                canvas.paste(
                    ghost,
                    (tile.cx - ghost.width // 2 + int(dx * 1.4),
                     tile.cy - ghost.height // 2 + int(dy * 1.4)),
                    ghost,
                )

            canvas.paste(
                image, (tile.cx - image.width // 2 + dx, tile.cy - image.height // 2 + dy), image
            )

    def _sub_layer(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        if not self.scene.sub:
            return
        progress = clamp01((t - self.sub_start) / max(0.05, self.entry_n))
        if progress <= 0:
            return
        font = _font(33, weight=600)
        text = self.scene.sub
        width = draw.textlength(text, font=font)
        x = (W - width) / 2
        y = self.sub_y - px(18 * (1 - ease_out_expo(progress)))
        draw.rounded_rectangle(
            [x - px(22), y - px(12), x + width + px(22), y + px(50)],
            radius=px(18), fill=(*_mix(self.wash, (0, 0, 0), 0.55), int(150 * progress)),
        )
        draw.text((x, y), text, font=font, fill=(*self.fg, int(255 * progress)))

    def _fit_font(
        self, draw: ImageDraw.ImageDraw, text: str, start: int, box_w: int, *, weight: int = 900
    ) -> ImageFont.ImageFont:
        """Largest display size at which `text` still fits the safe width."""
        for size in range(start, 32, -8):
            font = _font(size, display=True, weight=weight)
            if draw.textlength(text, font=font) <= box_w:
                return font
        return _font(32, display=True, weight=weight)

    def _chapter(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        """Section divider: a huge number, a rule that grows, then the title."""
        scene = self.scene
        box_w = W - (SAFE_X + 20) * 2
        number = scene.value or f"{self.index:02d}"

        progress = clamp01((t - 0.05) / 0.32)
        if progress > 0:
            font = self._fit_font(draw, number, 250, box_w)
            width = draw.textlength(number, font=font)
            slide = ease_out_expo(progress)
            x = (W - width) / 2 - px(240 * (1 - slide))
            draw.text(
                (x, px(430)), number, font=font, fill=(*self.accent_color, int(255 * progress))
            )

        rule = ease_out_expo(clamp01((t - 0.28) / 0.30))
        if rule > 0:
            half = px(150 * rule)
            draw.rounded_rectangle(
                [W // 2 - half, px(700), W // 2 + half, px(707)], radius=px(4),
                fill=(*self.fg, 220),
            )

        title = clamp01((t - 0.38) / 0.32)
        if title > 0 and scene.text:
            font = self._fit_font(draw, scene.text.upper(), 62, box_w, weight=800)
            width = draw.textlength(scene.text.upper(), font=font)
            lift = px(34 * (1 - ease_out_expo(title)))
            draw.text(
                ((W - width) / 2, px(760) + lift), scene.text.upper(), font=font,
                fill=(*self.fg, int(255 * title)),
            )

    def _stat(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        """One figure, told big — the fact scenes that carry a long clip."""
        scene = self.scene
        box_w = W - (SAFE_X + 20) * 2
        value = scene.value or scene.text

        progress = clamp01((t - 0.06) / 0.34)
        if progress > 0:
            # The figure counts up to its value — the number becomes the motion.
            shown = count_up(value, ease_out_expo(progress))
            font = self._fit_font(draw, value, 170, box_w)
            width = draw.textlength(shown, font=font)
            scale = max(0.4, ease_out_back(progress))
            drop = px(60 * (1 - scale))        # re-fitting per frame is costly
            draw.text(
                ((W - width) / 2, px(470) + drop), shown, font=font,
                fill=(*self.accent_color, int(255 * min(1.0, progress * 1.4))),
            )

        label = clamp01((t - 0.34) / 0.30)
        if label > 0 and scene.text and scene.value:
            font = _font(46, weight=700)
            width = draw.textlength(scene.text, font=font)
            lift = px(30 * (1 - ease_out_expo(label)))
            draw.text(
                ((W - width) / 2, px(700) + lift), scene.text, font=font,
                fill=(*self.fg, int(255 * label)),
            )

    def _split(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        """Two columns compared side by side — built for 'X vs Y' explanations."""
        scene = self.scene
        column = W // 2 - SAFE_X - px(26)
        mid = W // 2

        divider = ease_out_expo(clamp01((t - 0.04) / 0.30))
        if divider > 0:
            top, height = px(400), px(620 * divider)
            draw.rounded_rectangle(
                [mid - px(3), top, mid + px(3), top + height], radius=px(3),
                fill=(*self.accent_color, 210),
            )

        titles = ((scene.text, -1, 0.10), (scene.value, 1, 0.18))
        for index, (title, side, start) in enumerate(titles):
            if not title:
                continue
            progress = clamp01((t - start) / 0.30)
            if progress <= 0:
                continue
            slide = ease_out_expo(progress)
            font = self._fit_font(draw, title.upper(), 60, column - px(20), weight=900)
            width = draw.textlength(title.upper(), font=font)
            centre = mid + side * (column // 2 + px(14))
            x = centre - width / 2 + side * px(150 * (1 - slide))
            draw.text(
                (x, px(450)), title.upper(), font=font,
                fill=(*(self.accent_color if index == 0 else self.fg), int(255 * progress)),
            )

            line = scene.items[index] if index < len(scene.items) else ""
            if not line or t < start + 0.28:
                continue
            body_alpha = ease_out_cubic(clamp01((t - start - 0.28) / 0.30))
            body_font = _font(34, weight=600)
            for row, text in enumerate(_wrap_plain(draw, line, body_font, column - px(30))[:3]):
                text_w = draw.textlength(text, font=body_font)
                draw.text(
                    (centre - text_w / 2, px(560) + row * px(46)), text, font=body_font,
                    fill=(*self.fg, int(230 * body_alpha)),
                )

    def _code(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        """A console window typing itself — the most literal 'this is software' cue."""
        scene = self.scene
        x, y, w, h = SAFE_X + px(6), px(430), W - (SAFE_X + px(6)) * 2, px(520)

        frame = ease_out_expo(clamp01(t / 0.22))
        if frame <= 0:
            return
        height = int(h * frame)
        draw.rounded_rectangle(
            [x, y, x + w, y + height], radius=px(22),
            fill=(*_mix(self.wash, (0, 0, 0), 0.55), 205),
            outline=(*self.accent_color, 200), width=px(3),
        )
        if frame < 1:
            return
        draw.line(
            [(x, y + px(58)), (x + w, y + px(58))], fill=(*self.accent_color, 120), width=px(2)
        )
        for dot in range(3):
            cx = x + px(28) + dot * px(26)
            draw.ellipse(
                [cx - px(7), y + px(22), cx + px(7), y + px(36)], outline=(*self.fg, 170),
                width=px(2),
            )

        lines = [line for line in scene.items[:5] if line.strip()]
        if not lines:
            lines = [scene.text or "// kod"]
        total_chars = sum(len(line) for line in lines)
        typed = int(total_chars * clamp01((t - 0.24) / 0.52))

        font = _mono(30)
        cursor_pos = None
        used = 0
        for row, line in enumerate(lines):
            remaining = max(0, typed - used)
            shown = line[:remaining]
            used += len(line)
            if not shown:
                break
            ty = y + px(92) + row * px(46)
            # Cheap syntax colour: the first token is the keyword.
            head, _, tail = shown.partition(" ")
            draw.text((x + px(30), ty), head, font=font, fill=(*self.accent_color, 255))
            if tail:
                offset = draw.textlength(head + " ", font=font)
                draw.text((x + px(30) + offset, ty), tail, font=font, fill=(*self.fg, 240))
            cursor_pos = (x + px(30) + draw.textlength(shown, font=font) + px(4), ty)

        if cursor_pos and int(t * 6) % 2 == 0:            # blinking caret
            draw.rectangle(
                [cursor_pos[0], cursor_pos[1] + px(4),
                 cursor_pos[0] + px(16), cursor_pos[1] + px(34)],
                fill=(*self.accent_color, 220),
            )

        if scene.text and t > 0.30:
            alpha = ease_out_cubic(clamp01((t - 0.30) / 0.28))
            font = _font(40, weight=800)
            width = draw.textlength(scene.text, font=font)
            draw.text(
                ((W - width) / 2, px(320)), scene.text, font=font,
                fill=(*self.fg, int(255 * alpha)),
            )

    def _chrome(self, canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        """Brand tag pinned to the top — the clip is branded on every frame."""
        spec = self.spec
        if spec.logo:
            try:
                side = px(52)
                mark = Image.open(BytesIO(spec.logo)).convert("RGB").resize((side, side))
                mask = Image.new("L", (side, side), 0)
                ImageDraw.Draw(mask).rounded_rectangle(
                    [0, 0, side - 1, side - 1], radius=px(14), fill=255
                )
                canvas.paste(mark, (SAFE_X, px(74)), mask)
            except OSError:
                pass
        if spec.brand:
            draw.text(
                (SAFE_X + px(68), px(88)), spec.brand.upper(), font=_font(24, weight=800),
                fill=(*self.fg, 235),
            )

    def _outro(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, t: float) -> None:
        spec = self.spec
        if spec.logo:
            progress = clamp01((t - 0.04) / 0.36)
            if progress > 0:
                size = px(200 * max(0.05, ease_out_back(progress)))
                try:
                    logo = Image.open(BytesIO(spec.logo)).convert("RGB").resize((size, size))
                    mask = Image.new("L", (size, size), 0)
                    ImageDraw.Draw(mask).rounded_rectangle(
                        [0, 0, size - 1, size - 1], radius=max(1, size * 18 // 100), fill=255
                    )
                    canvas.paste(logo, ((W - size) // 2, px(330) - size // 2), mask)
                except OSError:
                    pass

        if t > 0.22:
            slide = ease_out_expo(clamp01((t - 0.22) / 0.30))
            font = _font(52, display=True, weight=900)
            text = self.scene.text or spec.brand
            width = draw.textlength(text, font=font)
            draw.text(
                ((W - width) / 2, px(520) + px(40 * (1 - slide))), text, font=font,
                fill=(*self.fg, int(255 * slide)),
            )
        if self.scene.sub and t > 0.36:
            alpha = ease_out_cubic(clamp01((t - 0.36) / 0.30))
            font = _font(32, weight=600)
            width = draw.textlength(self.scene.sub, font=font)
            draw.text(
                ((W - width) / 2, px(606)), self.scene.sub, font=font,
                fill=(*self.fg, int(230 * alpha)),
            )
        if spec.phone and t > 0.46:
            progress = ease_out_back(clamp01((t - 0.46) / 0.30))
            width = px(470 * max(0.05, progress))
            top = px(760)
            draw.rounded_rectangle(
                [(W - width) // 2, top, (W + width) // 2, top + px(92)], radius=px(22),
                fill=(*self.gold, 255),
            )
            if progress > 0.75:
                font = _font(40, weight=800)
                text_w = draw.textlength(spec.phone, font=font)
                draw.text(
                    ((W - text_w) / 2, top + px(24)), spec.phone, font=font,
                    fill=(*_rgb(spec.colors.get("on_accent", "#141414"), (20, 20, 20)), 255),
                )
        if spec.footer and t > 0.58:
            font = _font(30, weight=500)
            width = draw.textlength(spec.footer, font=font)
            draw.text(((W - width) / 2, px(892)), spec.footer, font=font, fill=(*self.fg, 215))


# --------------------------------------------------------------------------- #
# Quality control
# --------------------------------------------------------------------------- #


def _luminance(colour: tuple[int, int, int]) -> float:
    channels = []
    for value in colour:
        srgb = value / 255
        channels.append(srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG contrast between two colours — 4.5 is the readable threshold."""
    first, second = _luminance(a), _luminance(b)
    lighter, darker = max(first, second), min(first, second)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def qc_scene(renderer: _SceneRenderer, position: int, previous: _SceneRenderer | None) -> list[str]:
    """Catch the mistakes a human would spot on playback — before rendering 900 frames."""
    issues: list[str] = []
    scene = renderer.scene

    needed = reading_time(scene)
    if scene.duration < needed - 0.05:
        issues.append(
            f"{position}-sahna qisqa: {scene.duration:.1f}s, o'qish uchun {needed:.1f}s kerak"
        )

    ratio = contrast_ratio(renderer.fg, renderer.wash)
    if ratio < 4.0:
        issues.append(f"{position}-sahna kontrasti past ({ratio}:1)")

    for tile in renderer.tiles:
        left = tile.cx - tile.image.width // 2
        top = tile.cy - tile.image.height // 2
        if left < -px(20) or left + tile.image.width > W + px(20):
            issues.append(f"{position}-sahna matni yon chegaradan chiqdi")
            break
        if top < 0 or top + tile.image.height > H:
            issues.append(f"{position}-sahna matni tik chegaradan chiqdi")
            break

    if (
        previous is not None
        and renderer.photo_path is not None
        and renderer.photo_path == previous.photo_path
    ):
        issues.append(f"{position}-sahna fonи oldingisi bilan bir xil")
    return issues


@dataclass(slots=True)
class KineticResult:
    video: StoredFile
    cover: StoredFile | None = None
    issues: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def _cues_for(
    scene: Scene, renderer: _SceneRenderer, clock: float
) -> list[tuple[str, float, float]]:
    cues: list[tuple[str, float, float]] = [("whoosh", max(0.0, clock - 0.12), 0.95)]
    if scene.kind == "outro":
        cues.append(("riser", max(0.0, clock - 0.9), 0.7))
        cues.append(("impact", clock + 0.06, 1.0))
        cues.append(("pop", clock + 0.52, 0.6))
        return cues
    if scene.kind == "chapter":
        cues.append(("impact", clock + 0.08, 0.7))       # section markers hit harder
        cues.append(("tick", clock + 0.42, 0.5))
        return cues
    if scene.kind == "stat":
        cues.append(("pop", clock + 0.12, 0.95))
        return cues
    if scene.kind == "split":
        cues.append(("pop", clock + 0.14, 0.8))
        cues.append(("pop", clock + 0.34, 0.8))          # one per column
        return cues
    if scene.kind == "code":
        for step in range(4):                            # keystroke texture
            cues.append(("tick", clock + 0.3 + step * 0.28, 0.45))
        return cues
    if renderer.prop is not None:
        cues.append(("pop", clock + 0.22, 0.9))
    for beat in renderer.word_beats[:4]:
        cues.append(("tick", clock + beat * scene.duration, 0.55))
    return cues


async def render_kinetic(
    spec: KineticSpec,
    *,
    prefix: str = "kinetic",
    crf: int = 19,
    maxrate: str = "12M",
    bufsize: str = "24M",
) -> KineticResult:
    """Render every scene to frames, assemble with ffmpeg, mix SFX and music.

    `crf` trades size for quality — long clips use a higher value so a minute
    of video still fits comfortably under Telegram's 50 MB upload ceiling.
    """
    binary = ffmpeg_path()
    if binary is None:
        raise ConfigurationError("ffmpeg is not installed — kinetic rendering unavailable")
    if not spec.scenes:
        raise ConfigurationError("kinetic spec has no scenes")

    # Snap every scene to a whole number of beats: the cuts then land on the
    # pulse of the bed, which is what makes an edit feel deliberate.
    for scene in spec.scenes:
        scene.duration = snap_to_beat(scene.duration, spec.bpm)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        frame_no = 0
        clock = 0.0
        cues: list[tuple[str, float, float]] = []
        issues: list[str] = []
        cover: bytes | None = None
        previous: _SceneRenderer | None = None
        tail: Image.Image | None = None
        for index, scene in enumerate(spec.scenes):
            renderer = _SceneRenderer(scene, spec, index)
            issues.extend(qc_scene(renderer, index + 1, previous))
            previous = renderer
            frames = max(FPS // 2, int(scene.duration * FPS))
            cues.extend(_cues_for(scene, renderer, clock))
            cover_at = int(frames * 0.92)
            for i in range(frames):
                image = renderer.frame(i / frames, i)
                if renderer.transition == "whip" and tail is not None and i < WHIP_FRAMES:
                    # Both sides of the cut blur toward each other and cross.
                    # A straight dissolve reads as a slideshow; the blur is what
                    # makes it read as one camera move rather than two frames.
                    ratio = (i + 1) / (WHIP_FRAMES + 1)
                    radius = math.sin(math.pi * ratio) * px(11)
                    image = Image.blend(
                        tail.filter(ImageFilter.GaussianBlur(radius)),
                        image.filter(ImageFilter.GaussianBlur(radius)),
                        ratio,
                    )
                if i == frames - 1:
                    tail = image
                # subsampling=0 keeps 4:4:4 chroma. The default 4:2:0 halves
                # colour resolution, and gold text on charcoal is exactly the
                # case where that shows as fringing — before x264 even runs.
                image.save(tmp_path / f"f{frame_no:05d}.jpg", quality=96, subsampling=0)
                if index == 0 and i == cover_at:
                    # The hook, fully assembled: the frame a feed should show.
                    buffer = BytesIO()
                    image.save(buffer, format="JPEG", quality=95, subsampling=0)
                    cover = buffer.getvalue()
                frame_no += 1
            clock += frames / FPS

        # An external track replaces the synthesised bed; otherwise we play our own.
        bed = None if spec.music and spec.music.exists() else render_bed(
            bed_spec(clock, signature=spec.brand, subject=spec.subject,
                     bpm=spec.bpm, energy=spec.energy)
        )
        track = mix_soundtrack(cues, clock, tmp_path / "track.wav", bed=bed)
        command = [
            binary, "-y",
            "-framerate", str(FPS), "-i", str(tmp_path / "f%05d.jpg"),
            "-i", str(track),
        ]
        if spec.music and spec.music.exists():
            command += ["-stream_loop", "-1", "-i", str(spec.music)]
            filter_complex = (
                f"[2:a]volume=0.26,afade=t=out:st={max(0.0, clock - 1.4):.2f}:d=1.4[mus];"
                f"[1:a][mus]amix=inputs=2:normalize=0,{loudnorm_filter()}[aud]"
            )
            audio_map = ["-filter_complex", filter_complex, "-map", "[aud]"]
        else:
            # Without this the clip ships at whatever the synth happened to
            # produce — measured at -20 LUFS, six dB under everything else
            # in the feed, which reads as a quiet, cheap video on a phone.
            # The measurement pass is what makes it land on the target rather
            # than a dB under it; see `loudnorm_filter`.
            from app.services.video_editor import measure_loudness

            audio_map = [
                "-map", "1:a",
                "-af", loudnorm_filter(measured=await measure_loudness(track)),
            ]

        out_path = tmp_path / "out.mp4"
        command += [
            "-map", "0:v", *audio_map,
            "-t", f"{clock:.2f}",
            *video_args(crf=crf, fps=FPS, maxrate=maxrate, bufsize=bufsize),
            *audio_args(),
            "-movflags", "+faststart",
            str(out_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise PublishError(
                "ffmpeg", f"kinetic render failed: {stderr[-500:].decode(errors='replace')}"
            )
        data = out_path.read_bytes()

    storage = get_storage()
    stored = storage.save_bytes(data, prefix=prefix, content_type="video/mp4")
    cover_file = (
        storage.save_bytes(cover, prefix=f"{prefix}-cover", content_type="image/jpeg")
        if cover
        else None
    )
    log.info(
        "kinetic_rendered", scenes=len(spec.scenes), seconds=round(clock, 1),
        size=stored.size, resolution=f"{W}x{H}", issues=len(issues),
    )
    for issue in issues:
        log.warning("kinetic_qc", detail=issue)
    return KineticResult(video=stored, cover=cover_file, issues=issues)


async def mix_voiceover(video: Path, voice: Path, *, prefix: str = "kinetic-vo") -> StoredFile:
    """Lay a recorded voice over a finished clip, ducking the music under it.

    `sidechaincompress` pulls the existing SFX/music bed down whenever the voice
    speaks and lets it back up in the gaps — the same move a human editor makes.
    """
    binary = ffmpeg_path()
    if binary is None:
        raise ConfigurationError("ffmpeg is not installed — voice mixing unavailable")

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "voiced.mp4"
        filter_complex = (
            "[1:a]volume=1.5,aresample=44100[vo];"
            "[vo]asplit=2[vo1][vo2];"
            "[0:a][vo1]sidechaincompress=threshold=0.04:ratio=9:attack=15:release=350[bed];"
            "[bed][vo2]amix=inputs=2:duration=first:normalize=0[aud]"
        )
        command = [
            binary, "-y", "-i", str(video), "-i", str(voice),
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aud]",
            "-c:v", "copy", *audio_args(),
            "-movflags", "+faststart", str(out_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise PublishError(
                "ffmpeg", f"voice mix failed: {stderr[-500:].decode(errors='replace')}"
            )
        data = out_path.read_bytes()

    stored = get_storage().save_bytes(data, prefix=prefix, content_type="video/mp4")
    log.info("kinetic_voiceover_mixed", size=stored.size)
    return stored
