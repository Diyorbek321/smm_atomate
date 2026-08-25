"""Renders a promo *script* — a JSON scene description — into a finished clip.

This is the second video engine in the system, and it exists because the two
solve different problems.

:mod:`app.services.kinetic` draws every frame with Pillow. That is fast, has no
browser in the loop, and is what the daily volume runs on. What it cannot do
cheaply is the things CSS gives away: blend modes, masks, per-element blur,
glow, split layouts. Those are exactly what separates an agency-grade clip from
a caption on a background.

So this engine drives a real browser over an authored HTML template. It is
roughly 4x slower per second of output, which is the trade: it renders the
hero pieces, not the daily feed.

The *layout and timing are authored*, not generated. A script names a family
(see :mod:`app.services.promo_families`) and fills its slots with copy. A model
that could emit arbitrary geometry would emit bad geometry.

Audio deliberately reuses :mod:`app.services.kinetic`'s cue library and
:mod:`app.services.music`'s bed rather than growing a second sound identity —
and, incidentally, avoids a numpy dependency the service layer does not have.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.exceptions import ConfigurationError, PublishError
from app.core.logging import get_logger
from app.services.encoding import audio_args, loudnorm_filter, video_args
from app.services.kinetic import mix_soundtrack
from app.services.music import MusicSpec, render_bed
from app.services.storage import StoredFile, get_storage
from app.services.video import ffmpeg_path

log = get_logger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "promo"
TEMPLATE = TEMPLATE_DIR / "template.html"

#: JPEG rather than PNG for the intermediate frames: 600 lossless frames of
#: 1080x1920 is over a gigabyte, and quality 95 survives the x264 pass with
#: nothing visible left over.
FRAME_QUALITY = 95

#: How long a single clip may spend in the browser before we give up. A 20 s
#: script is ~100 s of capture; anything past this is a hang, not slow work.
RENDER_TIMEOUT = 600


#: Instagram carousel slide. Not 9:16 — a carousel is scrolled, not swiped
#: full-screen, and 4:5 is the tallest crop the feed shows without cutting.
CAROUSEL_SIZE = (1080, 1350)

#: The authored layouts target 1080x1920. A carousel frame is 30% shorter, so
#: everything shrinks rather than overflowing the bottom of the slide.
CAROUSEL_SCALE = 0.80


@dataclass(slots=True)
class CarouselResult:
    slides: list[StoredFile]
    issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PromoResult:
    video: StoredFile
    cover: StoredFile | None = None
    seconds: float = 0.0
    issues: list[str] = field(default_factory=list)


def _cues(script: dict) -> list[tuple[str, float, float]]:
    """Sound cues derived from the script's own cuts.

    The script is the single source of truth for timing, so the audio cannot
    drift out of sync with the edit the way a hand-authored bed would.
    """
    scenes = script["scenes"]
    duration = float(script["duration"])
    cuts = [float(s["at"][0]) for s in scenes]
    cues: list[tuple[str, float, float]] = []
    for index, cut in enumerate(cuts):
        cues.append(("whoosh", max(0.0, cut - 0.12), 0.95))
        if index:                                  # the opening needs no hit
            cues.append(("impact", cut + 0.04, 0.85))
    last = cuts[-1] if cuts else duration
    cues.append(("riser", max(0.0, last - 1.0), 0.7))
    cues.append(("pop", last + 0.5, 0.6))
    return cues


def _localise(script: dict) -> dict:
    """Rewrite asset paths to absolute file URLs.

    Props live under ``brand/<business>/props``, nowhere near the template, and
    a relative src would resolve against the template directory and silently
    render nothing.
    """
    out = json.loads(json.dumps(script))          # never mutate the caller's dict
    def fix(value: str | None) -> str | None:
        if not value or value.startswith(("http://", "https://", "file://", "data:")):
            return value
        path = Path(value)
        if not path.is_absolute():
            path = (TEMPLATE_DIR / path).resolve()
        return path.as_uri() if path.exists() else None

    if out.get("background"):
        out["background"] = fix(out["background"])
    for scene in out.get("scenes", []):
        if scene.get("prop", {}).get("src"):
            fixed = fix(scene["prop"]["src"])
            if fixed:
                scene["prop"]["src"] = fixed
            else:
                scene.pop("prop")                  # a missing prop is not a failure
        for line in scene.get("lines", []):
            if line.get("kind") == "photo" and line.get("src"):
                line["src"] = fix(line["src"]) or ""
    return out


async def _capture(script: dict, out_dir: Path) -> tuple[list[str], bytes | None]:
    """Drive the template frame by frame. Returns QC issues and a cover JPEG."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:                     # pragma: no cover
        raise ConfigurationError("playwright is not installed — promo rendering unavailable") from exc

    fps = int(script.get("fps", 30))
    width, height = script.get("size", [1080, 1920])
    total = round(fps * float(script["duration"]))
    cover_at = int(total * 0.10)                   # the hook, fully assembled
    cover: bytes | None = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--force-color-profile=srgb", "--disable-lcd-text"]
        )
        page = await browser.new_page(
            viewport={"width": width, "height": height}, device_scale_factor=1
        )
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        await page.goto(TEMPLATE.as_uri(), wait_until="networkidle")
        await page.evaluate("() => document.fonts.ready")
        await page.evaluate("s => window.build(s)", script)
        # build() only just inserted the <img> tags; a screenshot taken before
        # they decode renders the scene with holes in it.
        await page.wait_for_function(
            "() => [...document.images].every(i => i.complete && i.naturalWidth > 0)",
            timeout=20000,
        )
        # Fonts are only requested once build() puts text on the page, so this
        # is the first point they can be waited for — and fitting before they
        # land measures the fallback face and under-shrinks every line.
        await page.evaluate("() => document.fonts.ready")
        await page.evaluate("() => window.fit()")
        await page.wait_for_timeout(300)

        issues = [
            f"{i['scene']}-sahna «{i['text']}» {i['width']}px > {i['avail']}px"
            for i in await page.evaluate("() => window.measure()")
        ]
        for frame in range(total):
            await page.evaluate("t => window.setTime(t)", frame / fps)
            shot = await page.screenshot(
                path=str(out_dir / f"f{frame:05d}.jpg"),   # ffmpeg reads f%05d.jpg
                type="jpeg", quality=FRAME_QUALITY, animations="disabled",
            )
            if frame == cover_at:
                cover = shot
        await browser.close()
        issues.extend(f"sahifa xatosi: {e}" for e in errors)
    return issues, cover


def _settle(scene: dict) -> float:
    """When a scene is fully assembled — every line in, nothing leaving yet.

    A carousel slide is a single frozen moment, so it has to be the moment the
    scene is *finished*, not an arbitrary midpoint with half the copy still
    flying in.
    """
    start, end = (float(v) for v in scene["at"])
    span = end - start
    panes = scene.get("columns") or [scene]
    latest = 0.0
    for pane in panes:
        for line in pane.get("lines", []):
            latest = max(latest, float(line.get("at", 0.0)) + float(line.get("dur", 0.52)))
    if scene.get("prop"):
        latest = max(latest, 0.9)                  # props settle on a back-ease
    return start + min(latest + 0.25, max(0.3, span - 0.25))


async def render_carousel(
    script: dict,
    *,
    prefix: str = "carousel",
    size: tuple[int, int] = CAROUSEL_SIZE,
    unit_scale: float = CAROUSEL_SCALE,
) -> CarouselResult:
    """One still per scene, from the same authored families as the video.

    Carousels are posted about as often as feed images here, and were being
    drawn by a much simpler renderer. Reusing the promo families means every
    layout improvement lands in both places at once.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:                     # pragma: no cover
        raise ConfigurationError("playwright is not installed — carousel rendering unavailable") from exc
    if not script.get("scenes"):
        raise ConfigurationError("promo script has no scenes")

    localised = _localise(script)
    localised["size"] = list(size)
    localised["unitScale"] = unit_scale
    width, height = size
    shots: list[bytes] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--force-color-profile=srgb", "--disable-lcd-text"]
        )
        page = await browser.new_page(
            viewport={"width": width, "height": height}, device_scale_factor=1
        )
        await page.goto(TEMPLATE.as_uri(), wait_until="networkidle")
        await page.evaluate("() => document.fonts.ready")
        await page.evaluate("s => window.build(s)", localised)
        await page.wait_for_function(
            "() => [...document.images].every(i => i.complete && i.naturalWidth > 0)",
            timeout=20000,
        )
        await page.evaluate("() => document.fonts.ready")
        await page.evaluate("() => window.fit()")
        await page.wait_for_timeout(300)
        issues = [
            f"{i['scene']}-slayd [{i.get('axis', 'x')}] «{i['text']}» "
            f"{i['width']}px > {i['avail']}px"
            for i in await page.evaluate("() => window.measure()")
        ]
        for scene in localised["scenes"]:
            await page.evaluate("t => window.setTime(t)", _settle(scene))
            shots.append(await page.screenshot(type="jpeg", quality=94))
        await browser.close()

    storage = get_storage()
    slides = [
        storage.save_bytes(shot, prefix=f"{prefix}-{index + 1:02d}", content_type="image/jpeg")
        for index, shot in enumerate(shots)
    ]
    log.info("carousel_rendered", family=script.get("family", "?"), slides=len(slides),
             issues=len(issues))
    for issue in issues:
        log.warning("carousel_qc", detail=issue)
    return CarouselResult(slides=slides, issues=issues)


async def render_promo(script: dict, *, prefix: str = "promo", crf: int = 19) -> PromoResult:
    """Render one promo script into a stored MP4."""
    binary = ffmpeg_path()
    if binary is None:
        raise ConfigurationError("ffmpeg is not installed — promo rendering unavailable")
    if not script.get("scenes"):
        raise ConfigurationError("promo script has no scenes")

    localised = _localise(script)
    duration = float(localised["duration"])
    fps = int(localised.get("fps", 30))
    music = localised.get("music", {})

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        issues, cover = await asyncio.wait_for(
            _capture(localised, tmp_path), timeout=RENDER_TIMEOUT
        )

        bed = render_bed(MusicSpec(
            seconds=duration,
            bpm=int(music.get("bpm", 120)),
            energy=str(music.get("energy", "calm")),
            mood=str(music.get("mood", "calm")),
            key_shift=int(music.get("key_shift", 0)),
            rotation=int(music.get("rotation", 0)),
        ))
        track = mix_soundtrack(_cues(localised), duration, tmp_path / "track.wav", bed=bed)

        # Imported here rather than at module scope: video_editor pulls in the
        # caption stack, and a promo render has no business paying for it when
        # all it wants is one ffmpeg measurement.
        from app.services.video_editor import measure_loudness

        measured = await measure_loudness(track)

        out_path = tmp_path / "out.mp4"
        command = [
            binary, "-y",
            "-framerate", str(fps), "-i", str(tmp_path / "f%05d.jpg"),
            "-i", str(track),
            "-map", "0:v", "-map", "1:a",
            "-af", loudnorm_filter(measured=measured),
            "-t", f"{duration:.2f}",
            *video_args(crf=crf, fps=fps),
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
                "ffmpeg", f"promo render failed: {stderr[-500:].decode(errors='replace')}"
            )
        data = out_path.read_bytes()

    storage = get_storage()
    stored = storage.save_bytes(data, prefix=prefix, content_type="video/mp4")
    cover_file = (
        storage.save_bytes(cover, prefix=f"{prefix}-cover", content_type="image/jpeg")
        if cover else None
    )
    log.info(
        "promo_rendered", family=script.get("family", script.get("name", "?")),
        scenes=len(script["scenes"]), seconds=duration, size=stored.size,
        issues=len(issues),
    )
    for issue in issues:
        log.warning("promo_qc", detail=issue)
    return PromoResult(video=stored, cover=cover_file, seconds=duration, issues=issues)
