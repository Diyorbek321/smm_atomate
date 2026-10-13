"""Remotion engine — the render service draws the picture, this module adds sound.

The third browser-backed engine, next to :mod:`app.services.promo` (authored
HTML templates) and :mod:`app.services.kinetic` (Pillow). What Remotion buys is
React/SVG motion: drawn-on icons, springs, per-element blur, light leaks,
camera moves — the things that read as "motion designer" rather than
"template".

The service (``backend/remotion``, a separate container) returns a *muted*
MP4. Sound is laid here on purpose: the bed, the SFX and the loudness pass are
the same code every other engine uses, so a Remotion clip sounds like the rest
of what a business ships, and the delivery encode (BT.709 tags, bitrate
ceiling) is decided in one place — :mod:`app.services.encoding`.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import ConfigurationError, ProviderError, PublishError
from app.core.logging import get_logger
from app.services.encoding import audio_args, loudnorm_filter, video_args
from app.services.kinetic import mix_soundtrack
from app.services.music import MusicSpec, render_bed
from app.services.promo import PromoResult
from app.services.storage import get_storage
from app.services.video import ffmpeg_path

log = get_logger(__name__)

PROVIDER = "remotion"


def available() -> bool:
    return bool(settings.remotion_url.strip()) and ffmpeg_path() is not None


async def request_render(script: dict[str, Any], *, client: httpx.AsyncClient | None = None) -> bytes:
    """POST the props to the render service and return the muted MP4 bytes."""
    base = settings.remotion_url.strip().rstrip("/")
    if not base:
        raise ConfigurationError("REMOTION_URL is not configured — Remotion engine unavailable")
    body = {"composition": script["composition"], "props": script["props"]}
    owned = client is None
    client = client or httpx.AsyncClient(timeout=settings.remotion_timeout)
    try:
        response = await client.post(f"{base}/render", json=body)
    except httpx.TimeoutException as exc:
        raise ProviderError(PROVIDER, "render timed out") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(PROVIDER, f"render service unreachable: {exc.__class__.__name__}") from exc
    finally:
        if owned:
            await client.aclose()

    if response.status_code == 422:
        # A script the renderer refuses will be refused again: do not retry it.
        details = response.json().get("details") if response.content else None
        raise ProviderError(PROVIDER, "script rejected by renderer", details=details, retryable=False)
    if response.status_code != 200 or not response.headers.get("content-type", "").startswith("video/"):
        raise ProviderError(PROVIDER, f"render failed with HTTP {response.status_code}: {response.text[:200]}")
    return response.content


async def _ffmpeg(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise PublishError("ffmpeg", f"remotion mux failed: {stderr[-500:].decode(errors='replace')}")


def _cover_time(script: dict[str, Any]) -> float:
    """A frame from the logo scene, once the name has landed; else one second in."""
    for scene in script["props"]["scenes"]:
        if scene["type"] == "logo":
            return scene["at"][0] + min(1.5, (scene["at"][1] - scene["at"][0]) / 2)
    return 1.0


async def render_remotion(script: dict[str, Any], *, prefix: str = "remotion", crf: int = 19) -> PromoResult:
    """Render one script into a stored, sound-mixed MP4 plus a cover frame."""
    binary = ffmpeg_path()
    if binary is None:
        raise ConfigurationError("ffmpeg is not installed — Remotion rendering unavailable")

    duration = float(script["duration"])
    fps = int(script["props"]["fps"])
    music = script.get("music", {})
    silent = await request_render(script)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        picture = tmp_path / "picture.mp4"
        picture.write_bytes(silent)

        bed = render_bed(MusicSpec(
            seconds=duration,
            bpm=int(music.get("bpm", 120)),
            energy=str(music.get("energy", "drive")),
            mood=str(music.get("mood", "hopeful")),
            key_shift=int(music.get("key_shift", 0)),
        ))
        cues = [(str(name), float(at), float(gain)) for name, at, gain in script.get("cues", [])]
        track = mix_soundtrack(cues, duration, tmp_path / "track.wav", bed=bed)

        # Imported late for the same reason as in promo: video_editor pulls in
        # the caption stack, and one loudness measurement does not need it.
        from app.services.video_editor import measure_loudness

        measured = await measure_loudness(track)
        out_path = tmp_path / "out.mp4"
        await _ffmpeg(
            binary, "-y", "-i", str(picture), "-i", str(track),
            "-map", "0:v", "-map", "1:a",
            "-af", loudnorm_filter(measured=measured),
            "-t", f"{duration:.2f}",
            *video_args(crf=crf, fps=fps), *audio_args(),
            "-movflags", "+faststart", str(out_path),
        )
        cover_path = tmp_path / "cover.jpg"
        await _ffmpeg(binary, "-y", "-ss", f"{_cover_time(script):.2f}", "-i", str(picture),
                      "-frames:v", "1", "-q:v", "3", str(cover_path))
        data, cover = out_path.read_bytes(), cover_path.read_bytes()

    storage = get_storage()
    stored = storage.save_bytes(data, prefix=prefix, content_type="video/mp4")
    cover_file = storage.save_bytes(cover, prefix=f"{prefix}-cover", content_type="image/jpeg")
    log.info("remotion_rendered", scenes=len(script["props"]["scenes"]), seconds=duration, size=stored.size)
    return PromoResult(video=stored, cover=cover_file, seconds=duration)
