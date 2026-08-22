"""One place where "how do we encode video for delivery" is decided.

Telegram and Instagram re-encode everything they receive, so what leaves this
system is a *master*, not the final file — it has to survive a second lossy
pass. Two decisions follow from that:

* a bitrate ceiling well above what the clip needs, so the platform's encoder
  is handed clean input rather than our own compression artefacts;
* explicit BT.709 colour tags. An untagged stream is *guessed at* by the
  receiving transcoder — usually as BT.601 — which shifts hue and flattens
  contrast. That is the ordinary reason a clip looks right in the renderer and
  washed out on a phone.

Intermediate files inside our own pipeline are a separate case: they are
encoded again before anyone sees them, so they use a near-transparent CRF and
a fast preset. Generation loss stacks, and a temp file is cheap.
"""

from __future__ import annotations

from app.core.config import settings

#: Colour is *described* here, never converted: every frame this system
#: produces is already sRGB / BT.709 primaries.
COLOUR_TAGS: tuple[str, ...] = (
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-color_range", "tv",
)

#: Quality of files that will be re-encoded by a later stage of our pipeline.
INTERMEDIATE_CRF = 16
INTERMEDIATE_PRESET = "veryfast"


def video_args(
    *,
    crf: int | None = None,
    preset: str | None = None,
    fps: int = 30,
    maxrate: str | None = "12M",
    bufsize: str | None = "24M",
) -> list[str]:
    """ffmpeg output arguments for an H.264 stream meant for social delivery.

    Defaults come from settings so render time can be traded for quality
    without touching code (``VIDEO_CRF`` / ``VIDEO_PRESET``).
    """
    args = [
        "-c:v", "libx264",
        "-preset", preset or settings.video_preset,
        "-crf", str(settings.video_crf if crf is None else crf),
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        # A keyframe every two seconds: platforms cut and seek on them, and a
        # long GOP is where their re-encode loses the most detail.
        "-g", str(max(2, fps * 2)),
        "-keyint_min", str(max(1, fps)),
    ]
    if maxrate and bufsize:
        # Capped CRF: constant quality until the bitrate ceiling, which keeps
        # a busy motion scene from ballooning past what Telegram will accept.
        args += ["-maxrate", maxrate, "-bufsize", bufsize]
    args += list(COLOUR_TAGS)
    return args


def intermediate_video_args(*, fps: int = 30) -> list[str]:
    """Near-transparent settings for a file another stage will encode again."""
    return video_args(
        crf=INTERMEDIATE_CRF,
        preset=INTERMEDIATE_PRESET,
        fps=fps,
        maxrate=None,
        bufsize=None,
    )


def audio_args(*, bitrate: str | None = None, rate: int = 48000, channels: int = 2) -> list[str]:
    """AAC settings for delivery.

    192k stereo is the point where the platforms' own re-encode stops being
    audible on music beds; 160k was already showing on cymbals and risers.
    """
    return [
        "-c:a", "aac",
        "-b:a", bitrate or settings.audio_bitrate,
        "-ar", str(rate),
        "-ac", str(channels),
    ]
