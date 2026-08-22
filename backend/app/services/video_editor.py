"""Video editor — turns footage the owner shot into a publishable clip.

The owner films something on a phone and sends it to the bot; this module
does what a junior editor would do by hand:

    probe → cut dead air → reframe to 9:16 → colour polish → clean the audio
          → burn brand-styled subtitles → lay a music bed under the speech
          → add the brand intro / outro and a corner logo

Every stage is optional and degrades on its own: no speech means no subtitles,
no ffmpeg means no edit at all, and a stage that fails is recorded in the
report rather than losing the whole job. Only Standard and Pro tiers reach
this code — see app/core/plans.py.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.exceptions import ConfigurationError, ProviderError, PublishError
from app.core.logging import get_logger
from app.services.encoding import audio_args, intermediate_video_args, video_args
from app.services.video import ffmpeg_path

log = get_logger(__name__)

WIDTH, HEIGHT = 1080, 1920
FPS = 30
#: Caption geometry. The box is measured, not guessed: a character count
#: cannot know that "MMM" is twice "iii", and ASS WrapStyle 2 does not wrap on
#: its own — anything too wide simply runs off the side of the frame.
CAPTION_FONT = "DejaVu Sans"
CAPTION_FONT_SIZE = 64
CAPTION_MARGIN = 90
CAPTION_BOTTOM = 320
CAPTION_OUTLINE = 5
CAPTION_BOX = WIDTH - 2 * CAPTION_MARGIN - 2 * CAPTION_OUTLINE - 2
CAPTION_LINES = 2
#: Social feeds normalise what they receive to about -14 LUFS. Delivering
#: -16 is not "safer" — it just arrives quieter than everything around it.
LOUDNESS_TARGET = -14.0
TRUE_PEAK = -1.5
LOUDNESS_RANGE = 11
#: afftdn defaults to -50 dB; the -24 this used to run at treats far more of
#: the signal as noise, which is what makes phone speech sound underwater.
NOISE_FLOOR_DB = -32

#: A word spoken faster than this still gets a readable moment on screen.
MIN_CUE_SEC = 0.12
#: How long a caption stays up when the transcript gives no usable end time.
DEFAULT_CUE_SEC = 1.4
AUDIO_RATE = 48000

#: Anything quieter than this for longer than `SILENCE_MIN_SEC` is dead air.
SILENCE_NOISE_DB = -32
SILENCE_MIN_SEC = 0.6
#: Keep a breath either side of a cut so speech never sounds clipped.
SILENCE_PAD_SEC = 0.18
#: Fragments shorter than this are not worth keeping on their own.
MIN_SEGMENT_SEC = 0.45
#: Refuse to trim if it would gut the clip — the footage is probably B-roll.
MAX_TRIM_RATIO = 0.55
MIN_RESULT_SEC = 3.0

#: Portrait enough to crop; anything wider gets a blurred backdrop instead.
PORTRAIT_RATIO = 1.25

#: Brand card lengths — long enough to register, short enough not to bore.
INTRO_SEC = 1.2
OUTRO_SEC = 2.6


@dataclass(frozen=True, slots=True)
class EditSettings:
    """What the owner's tier and preferences turned on."""

    trim_silence: bool = True
    reframe: bool = True
    colour: bool = True
    clean_audio: bool = True
    subtitles: bool = True
    #: Highlight each word as it is spoken. Needs word timings from Whisper;
    #: without them the caption is still shown, just without the highlight.
    karaoke: bool = True
    music: bool = True
    brand_frames: bool = True


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration: float
    width: int
    height: int
    has_audio: bool

    @property
    def is_portrait(self) -> bool:
        return self.width > 0 and (self.height / self.width) >= PORTRAIT_RATIO


@dataclass(slots=True)
class EditReport:
    """What actually happened — surfaced to the owner with the result."""

    source_seconds: float = 0.0
    final_seconds: float = 0.0
    trimmed_seconds: float = 0.0
    subtitle_lines: int = 0
    stages: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def done(self, stage: str) -> None:
        self.stages.append(stage)

    def skip(self, stage: str, reason: str) -> None:
        self.skipped.append(f"{stage}: {reason}")


# --------------------------------------------------------------------------- #
# Pure helpers — no ffmpeg, no I/O, so they can be tested directly
# --------------------------------------------------------------------------- #
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video:.*?,\s*(\d+)x(\d+)")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio:")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+\.?\d*)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+\.?\d*)")


def parse_media_info(stderr: str) -> MediaInfo:
    """Read duration/size/audio out of `ffmpeg -i` output.

    ffprobe is not used on purpose: the static build in this image segfaults.
    """
    duration = 0.0
    if match := _DURATION_RE.search(stderr):
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    width = height = 0
    if match := _VIDEO_RE.search(stderr):
        width, height = int(match.group(1)), int(match.group(2))

    return MediaInfo(duration, width, height, bool(_AUDIO_RE.search(stderr)))


def parse_silences(stderr: str) -> list[tuple[float, float]]:
    """Pair up `silence_start` / `silence_end` lines from silencedetect."""
    starts = [float(v) for v in _SILENCE_START_RE.findall(stderr)]
    ends = [float(v) for v in _SILENCE_END_RE.findall(stderr)]
    pairs: list[tuple[float, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else None
        if end is None or end <= start:
            continue
        pairs.append((max(0.0, start), end))
    return pairs


def keep_segments(duration: float, silences: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Invert the silences into the spans worth keeping.

    Returns an empty list when trimming is not worth it — the caller then
    leaves the footage alone rather than mangling it.
    """
    if duration <= 0:
        return []

    segments: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in sorted(silences):
        speech_end = min(duration, start + SILENCE_PAD_SEC)
        if speech_end - cursor >= MIN_SEGMENT_SEC:
            segments.append((cursor, speech_end))
        cursor = max(cursor, min(duration, end - SILENCE_PAD_SEC))
    if duration - cursor >= MIN_SEGMENT_SEC:
        segments.append((cursor, duration))

    kept = sum(end - start for start, end in segments)
    if not segments or kept < MIN_RESULT_SEC:
        return []
    if (duration - kept) / duration > MAX_TRIM_RATIO:
        return []
    if len(segments) == 1 and segments[0] == (0.0, duration):
        return []
    return segments


def trim_filter(segments: list[tuple[float, float]], *, with_audio: bool) -> str:
    """filter_complex that concatenates the kept spans back together."""
    parts: list[str] = []
    for index, (start, end) in enumerate(segments):
        parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}];"
        )
        if with_audio:
            parts.append(
                f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}];"
            )
    streams = "".join(
        f"[v{i}][a{i}]" if with_audio else f"[v{i}]" for i in range(len(segments))
    )
    outputs = "[tv][ta]" if with_audio else "[tv]"
    parts.append(f"{streams}concat=n={len(segments)}:v=1:a={1 if with_audio else 0}{outputs}")
    return "".join(parts)


def reframe_filter(info: MediaInfo) -> str:
    """Fit any aspect ratio into 9:16.

    Portrait footage is scaled and cropped; landscape sits on a blurred,
    enlarged copy of itself, which is what a hand editor would do rather than
    leaving black bars.
    """
    if info.is_portrait or info.width == 0:
        return (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT}"
        )
    return (
        f"split=2[blur][fg];"
        f"[blur]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},gblur=sigma=28,eq=brightness=-0.06[bg];"
        f"[fg]scale={WIDTH}:-2[fgs];"
        f"[bg][fgs]overlay=(W-w)/2:(H-h)/2"
    )


def colour_filter() -> str:
    """A gentle grade — phone footage is usually flat and slightly soft."""
    return "eq=contrast=1.06:saturation=1.12:brightness=0.012,unsharp=5:5:0.55:5:5:0.0"


def audio_filter(measured: dict[str, str] | None = None) -> str:
    """Denoise, drop rumble, then normalise to the loudness social feeds expect.

    Given a first-pass measurement, loudnorm switches to its linear mode: it
    applies one known gain instead of guessing its way through the file, and
    lands on the target instead of near it. Without one it still works, just
    less exactly — a measurement failure must not cost the clip its audio.
    """
    chain = [f"afftdn=nf={NOISE_FLOOR_DB}", "highpass=f=90"]
    norm = f"loudnorm=I={LOUDNESS_TARGET}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}"
    if measured:
        norm += (
            f":measured_I={measured['input_i']}"
            f":measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}"
            f":measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}"
            ":linear=true"
        )
    chain.append(norm)
    return ",".join(chain)


async def measure_loudness(path: Path) -> dict[str, str] | None:
    """First pass: what this audio actually measures, as loudnorm reports it."""
    try:
        stderr = await _run(
            [
                _binary(), "-hide_banner", "-nostats", "-i", str(path), "-vn",
                "-af", f"loudnorm=I={LOUDNESS_TARGET}:TP={TRUE_PEAK}:"
                       f"LRA={LOUDNESS_RANGE}:print_format=json",
                "-f", "null", "-",
            ],
            stage="loudness",
        )
    except (PublishError, ConfigurationError) as exc:
        log.warning("loudness_measure_failed", error=str(exc)[:200])
        return None

    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        measured = json.loads(stderr[start : end + 1])
    except ValueError:
        return None

    needed = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    if any(key not in measured for key in needed):
        return None
    # A silent track measures -inf, and loudnorm cannot act on that.
    if any(str(measured[key]).lstrip("-").startswith("inf") for key in needed):
        return None
    log.info("loudness_measured", integrated=measured["input_i"], peak=measured["input_tp"])
    return {key: str(measured[key]) for key in needed}


#: Whisper's Uzbek drifts into Turkish-looking spellings ("gelecekte" for
#: "kelajakda"), so the raw transcript is proof-read before it is burned in.
CORRECTION_SYSTEM = (
    "Sen o'zbek tilidagi avtomatik transkriptni tuzatuvchisan. "
    "Nutqni tanib olish dasturi so'zlarni noto'g'ri yozgan bo'lishi mumkin "
    "(turkcha yoki qozoqcha imloga o'xshab ketadi). Vazifang: har bir satrni "
    "TO'G'RI O'ZBEK IMLOSIDA qayta yozish. "
    "QAT'IY QOIDALAR: satrlar sonini o'zgartirma, tartibini buzma, "
    "yangi ma'no qo'shma, satrni qisqartirma yoki uzaytirma — faqat imlo va "
    "so'zlarni tuzat. Agar satr allaqachon to'g'ri bo'lsa, o'zgarishsiz qaytar. "
    "Javobni FAQAT raqamlangan ro'yxat sifatida ber: '1. matn' ko'rinishida."
)

_NUMBERED_RE = re.compile(r"^\s*(\d+)[.):]\s*(.+)$")


def parse_corrections(text: str, expected: int) -> list[str] | None:
    """Read the model's numbered list back, or give up and keep the original."""
    corrected: dict[int, str] = {}
    for line in text.splitlines():
        match = _NUMBERED_RE.match(line)
        if not match:
            continue
        index = int(match.group(1))
        value = match.group(2).strip()
        if 1 <= index <= expected and value:
            corrected[index] = value
    if len(corrected) != expected:
        return None
    return [corrected[i] for i in range(1, expected + 1)]


async def correct_transcript(segments: list[dict], language: str = "uz") -> list[dict]:
    """Proof-read the transcript, keeping every timing exactly as it was.

    Fails soft in both directions: any error, or a reply that does not line up
    one-to-one with the input, leaves the original text untouched.
    """
    if not segments or language != "uz":
        return segments

    numbered = "\n".join(
        f"{index}. {str(segment.get('text', '')).strip()}"
        for index, segment in enumerate(segments, start=1)
    )
    try:
        from app.services.llm import get_llm

        result = await get_llm().generate_text(
            numbered, system=CORRECTION_SYSTEM, temperature=0.1
        )
    except Exception as exc:                      # a bad transcript beats none
        log.warning("transcript_correction_failed", error=str(exc)[:200])
        return segments

    corrected = parse_corrections(result.text, len(segments))
    if corrected is None:
        log.warning("transcript_correction_misaligned", expected=len(segments))
        return segments

    log.info("transcript_corrected", lines=len(corrected))
    return [{**segment, "text": text} for segment, text in zip(segments, corrected, strict=True)]


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def _bgr(hex_value: str, fallback: str) -> str:
    """CSS #RRGGBB -> the BBGGRR order ASS uses."""
    value = (hex_value or "").lstrip("#")
    if len(value) != 6:
        value = fallback
    return f"{value[4:6]}{value[2:4]}{value[0:2]}"


def _ass_colour(hex_value: str, fallback: str = "FFFFFF") -> str:
    """Style-block form, with the alpha byte."""
    return f"&H00{_bgr(hex_value, fallback)}"


def _inline_colour(hex_value: str, fallback: str = "FFFFFF") -> str:
    """Override form used inside a line: ``{\\c&HBBGGRR&}``."""
    return f"&H{_bgr(hex_value, fallback)}&"


def _ass_escape(text: str) -> str:
    """Braces open an override block in ASS; a caption must not."""
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


_measurer: Any = None


def caption_width(text: str) -> float:
    """Rendered width of a caption line, in the video's own pixel space.

    libass draws with the same font file Pillow measures here, and PlayResX
    equals the frame width, so one measured pixel is one frame pixel. If the
    font cannot be loaded the estimate degrades to an average advance rather
    than failing the edit.
    """
    global _measurer
    if _measurer is None:
        try:
            from PIL import Image, ImageDraw

            from app.services.video import _font

            draw = ImageDraw.Draw(Image.new("L", (8, 8)))
            font = _font(CAPTION_FONT_SIZE, bold=True)
            _measurer = lambda value: float(draw.textlength(value, font=font))  # noqa: E731
        except Exception as exc:
            log.warning("caption_measure_unavailable", error=str(exc)[:200])
            _measurer = lambda value: len(value) * CAPTION_FONT_SIZE * 0.58  # noqa: E731
    return _measurer(text)


def layout_words(
    words: list[dict],
    box: float = CAPTION_BOX,
    max_lines: int = CAPTION_LINES,
    measure: Callable[[str], float] = caption_width,
) -> list[list[list[dict]]]:
    """Greedy-wrap words into chunks of at most ``max_lines`` lines.

    Returns chunks -> lines -> words. Nothing is ever dropped: a long sentence
    becomes several chunks shown one after another. The old two-line clamp
    silently threw away everything a speaker said past the second line.
    """
    chunks: list[list[list[dict]]] = []
    lines: list[list[dict]] = []
    line: list[dict] = []
    text = ""
    for word in words:
        token = str(word.get("word", "")).strip()
        if not token:
            continue
        candidate = f"{text} {token}".strip()
        if line and measure(candidate) > box:
            lines.append(line)
            line, candidate = [], token
            if len(lines) == max_lines:
                chunks.append(lines)
                lines = []
        line.append(word)
        text = candidate
    if line:
        lines.append(line)
    if lines:
        chunks.append(lines)
    return chunks


def segment_words(segment: dict) -> tuple[list[dict], bool]:
    """The segment's words with timings, and whether those timings are real.

    Whisper's word list is paired back onto the *corrected* text, because the
    proof-reading pass rewrites Uzbek spelling that Whisper mangles and the
    caption has to show the corrected wording. When the two do not line up
    one-to-one the words are spread across the segment instead — enough to wrap
    the caption properly, but not enough to highlight: a highlight landing on
    the wrong word is worse than no highlight at all.
    """
    tokens = str(segment.get("text", "")).split()
    if not tokens:
        return [], False

    timed = [w for w in (segment.get("words") or []) if str(w.get("word", "")).strip()]
    if len(timed) == len(tokens):
        return [
            {"word": token, "start": float(w.get("start", 0.0)), "end": float(w.get("end", 0.0))}
            for token, w in zip(tokens, timed, strict=True)
        ], True

    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", 0.0))
    if end <= start:                       # a broken or missing end still shows
        end = start + DEFAULT_CUE_SEC
    span = end - start
    total = sum(len(token) for token in tokens) or 1
    spread, cursor = [], start
    for token in tokens:
        share = span * len(token) / total
        spread.append({"word": token, "start": cursor, "end": cursor + share})
        cursor += share
    return spread, False


def _chunk_text(chunk: list[list[dict]], highlight: dict | None, base: str, accent: str) -> str:
    rendered = []
    for line in chunk:
        parts = []
        for word in line:
            token = _ass_escape(str(word.get("word", "")).strip())
            if highlight is not None and word is highlight:
                parts.append(f"{{\\c{accent}}}{token}{{\\c{base}}}")
            else:
                parts.append(token)
        rendered.append(" ".join(parts))
    return "\\N".join(rendered)


def build_ass(segments: list[dict], colours: dict[str, str], *, karaoke: bool = True) -> str:
    """Brand-styled subtitles: ivory text, brand-coloured outline, bottom third.

    With word timings each word turns brand-coloured as it is spoken — the
    convention every social feed now reads as "edited". Only the colour
    changes: scaling or emboldening the active word would re-flow the line and
    make the whole caption twitch.
    """
    primary = _ass_colour("FFFFFF")
    outline = _ass_colour(colours.get("primary", ""), fallback="141414")
    accent = _ass_colour(colours.get("accent", ""), fallback="C9A227")
    base_inline = _inline_colour("FFFFFF")
    accent_inline = _inline_colour(colours.get("accent", ""), fallback="C9A227")

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {WIDTH}\nPlayResY: {HEIGHT}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Brand,{CAPTION_FONT},{CAPTION_FONT_SIZE},{primary},{accent},{outline},"
        f"&H64000000,-1,0,0,0,100,100,0.6,0,1,{CAPTION_OUTLINE},2,2,"
        f"{CAPTION_MARGIN},{CAPTION_MARGIN},{CAPTION_BOTTOM},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines: list[str] = []
    for segment in segments:
        words, timed = segment_words(segment)
        laid_out = layout_words(words)
        flattened = [[word for line in chunk for word in line] for chunk in laid_out]
        for position, chunk in enumerate(laid_out):
            flat = flattened[position]
            if not flat:
                continue
            # Hold the last word of a chunk until the next chunk takes over,
            # otherwise the caption blinks out for a frame between them.
            following = flattened[position + 1] if position + 1 < len(flattened) else []
            hand_over = float(following[0]["start"]) if following else None
            if karaoke and timed:
                for index, word in enumerate(flat):
                    start = float(word["start"])
                    if index + 1 < len(flat):
                        end = float(flat[index + 1]["start"])
                    else:
                        end = hand_over if hand_over is not None else float(word["end"])
                    if end <= start:
                        end = start + MIN_CUE_SEC
                    text = _chunk_text(chunk, word, base_inline, accent_inline)
                    lines.append(
                        f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Brand,,0,0,0,,{text}"
                    )
            else:
                start = float(flat[0]["start"])
                end = hand_over if hand_over is not None else float(flat[-1]["end"])
                if end <= start:
                    end = start + DEFAULT_CUE_SEC
                text = _chunk_text(chunk, None, base_inline, accent_inline)
                lines.append(
                    f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Brand,,0,0,0,,{text}"
                )
    return header + "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# ffmpeg stages
# --------------------------------------------------------------------------- #
async def _run(command: list[str], *, stage: str) -> str:
    """Run ffmpeg and return stderr (where it writes everything useful)."""
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    text = stderr.decode(errors="replace")
    if process.returncode not in (0, None):
        raise PublishError("ffmpeg", f"{stage} failed: {text[-800:]}", retryable=False)
    return text


async def probe(path: Path) -> MediaInfo:
    binary = _binary()
    # `-i` alone exits non-zero ("at least one output file") but still prints
    # the stream table, which is all we need.
    process = await asyncio.create_subprocess_exec(
        binary, "-hide_banner", "-i", str(path),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    info = parse_media_info(stderr.decode(errors="replace"))
    if info.duration <= 0:
        raise PublishError("ffmpeg", "could not read the video (corrupt or unsupported)", retryable=False)
    return info


async def detect_silences(path: Path) -> list[tuple[float, float]]:
    stderr = await _run(
        [
            _binary(), "-hide_banner", "-nostats", "-i", str(path),
            "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_SEC}",
            "-f", "null", "-",
        ],
        stage="silencedetect",
    )
    return parse_silences(stderr)


async def extract_audio(path: Path, target: Path) -> bool:
    """Mono 16 kHz m4a — small enough to post to Whisper without waiting."""
    try:
        await _run(
            [
                _binary(), "-y", "-hide_banner", "-i", str(path),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "48k",
                str(target),
            ],
            stage="extract_audio",
        )
    except PublishError:
        return False
    return target.exists() and target.stat().st_size > 0


async def normalise(
    source: Path,
    target: Path,
    info: MediaInfo,
    settings_: EditSettings,
    segments: list[tuple[float, float]],
    report: EditReport,
    measured: dict[str, str] | None = None,
) -> None:
    """One pass: trim, reframe, grade, clean the audio."""
    with_audio = info.has_audio
    video_chain: list[str] = []
    if settings_.reframe:
        video_chain.append(reframe_filter(info))
    if settings_.colour:
        video_chain.append(colour_filter())
    video_chain.append(f"fps={FPS},format=yuv420p")

    command = [_binary(), "-y", "-hide_banner", "-i", str(source)]
    audio_chain = audio_filter(measured) if (with_audio and settings_.clean_audio) else "anull"

    if segments:
        graph = trim_filter(segments, with_audio=with_audio)
        graph += f";[tv]{','.join(video_chain)}[v]"
        if with_audio:
            graph += f";[ta]{audio_chain},aresample={AUDIO_RATE}[a]"
        command += ["-filter_complex", graph, "-map", "[v]"]
        command += ["-map", "[a]"] if with_audio else []
    else:
        command += ["-vf", ",".join(video_chain)]
        if with_audio:
            command += ["-af", f"{audio_chain},aresample={AUDIO_RATE}"]

    if not with_audio:
        # Downstream stages assume an audio track exists; give it a silent one.
        command += ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo", "-shortest"]

    command += [
        *intermediate_video_args(fps=FPS),
        *audio_args(rate=AUDIO_RATE),
        "-movflags", "+faststart", str(target),
    ]
    await _run(command, stage="normalise")
    report.done("trim+reframe+colour" if segments else "reframe+colour")


async def burn_subtitles(source: Path, target: Path, ass_path: Path) -> None:
    escaped = str(ass_path).replace(":", r"\:")
    await _run(
        [
            _binary(), "-y", "-hide_banner", "-i", str(source),
            "-vf", f"subtitles='{escaped}'",
            *intermediate_video_args(fps=FPS),
            "-c:a", "copy", "-movflags", "+faststart", str(target),
        ],
        stage="subtitles",
    )


async def add_music(source: Path, target: Path, music: Path, *, speech: bool) -> None:
    """Lay the bed under the clip, ducking it whenever someone speaks."""
    if speech:
        graph = (
            "[1:a]volume=0.30,afade=t=out:st=0:d=0[bed0];"
            "[bed0][0:a]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400[bed];"
            "[0:a][bed]amix=inputs=2:duration=first:dropout_transition=0,"
            f"aresample={AUDIO_RATE}[a]"
        )
    else:
        graph = f"[1:a]volume=0.55,aresample={AUDIO_RATE}[a]"

    await _run(
        [
            _binary(), "-y", "-hide_banner",
            "-i", str(source), "-stream_loop", "-1", "-i", str(music),
            "-filter_complex", graph,
            "-map", "0:v", "-map", "[a]", "-shortest",
            "-c:v", "copy", *audio_args(rate=AUDIO_RATE), str(target),
        ],
        stage="music",
    )


async def add_brand_frames(
    source: Path, target: Path, intro: Path | None, outro: Path | None, watermark: Path | None
) -> None:
    """Corner logo for the whole clip, plus an intro sting and an outro card.

    `concat` refuses segments whose size, SAR, sample rate or channel layout
    differ, so every piece is forced through the same normalisation first.
    """
    video_norm = f"scale={WIDTH}:{HEIGHT},setsar=1,fps={FPS},format=yuv420p"
    audio_norm = f"aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=stereo"

    command = [_binary(), "-y", "-hide_banner", "-i", str(source)]
    next_input = 1
    intro_index = outro_index = watermark_index = None

    if intro is not None:
        command += ["-loop", "1", "-t", str(INTRO_SEC), "-i", str(intro)]
        intro_index, next_input = next_input, next_input + 1
    if outro is not None:
        command += ["-loop", "1", "-t", str(OUTRO_SEC), "-i", str(outro)]
        outro_index, next_input = next_input, next_input + 1
    if watermark is not None:
        command += ["-i", str(watermark)]
        watermark_index, next_input = next_input, next_input + 1

    parts: list[str] = []
    if watermark_index is not None:
        parts.append(f"[0:v]{video_norm}[bodyraw];[bodyraw][{watermark_index}:v]overlay=W-w-46:56[bodyv]")
    else:
        parts.append(f"[0:v]{video_norm}[bodyv]")
    parts.append(f"[0:a]{audio_norm}[bodya]")

    video_pieces: list[str] = []
    audio_pieces: list[str] = []

    if intro_index is not None:
        parts.append(f"[{intro_index}:v]{video_norm},fade=t=out:st={INTRO_SEC - 0.3:.2f}:d=0.3[introv]")
        parts.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo:d={INTRO_SEC},{audio_norm}[introa]")
        video_pieces.append("[introv]")
        audio_pieces.append("[introa]")

    video_pieces.append("[bodyv]")
    audio_pieces.append("[bodya]")

    if outro_index is not None:
        parts.append(f"[{outro_index}:v]{video_norm},fade=t=in:st=0:d=0.3[outrov]")
        parts.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo:d={OUTRO_SEC},{audio_norm}[outroa]")
        video_pieces.append("[outrov]")
        audio_pieces.append("[outroa]")

    interleaved = "".join(v + a for v, a in zip(video_pieces, audio_pieces, strict=True))
    parts.append(f"{interleaved}concat=n={len(video_pieces)}:v=1:a=1[v][a]")

    command += [
        "-filter_complex", ";".join(parts),
        "-map", "[v]", "-map", "[a]",
        *video_args(fps=FPS),
        *audio_args(rate=AUDIO_RATE),
        "-movflags", "+faststart", str(target),
    ]
    await _run(command, stage="brand_frames")


def _binary() -> str:
    binary = ffmpeg_path()
    if binary is None:
        raise ConfigurationError("ffmpeg is not installed — video editing unavailable")
    return binary


# --------------------------------------------------------------------------- #
# Brand frames
# --------------------------------------------------------------------------- #
def _brand_card(
    colours: dict[str, str],
    logo: bytes | None,
    *,
    title: str = "",
    lines: tuple[str, ...] = (),
) -> bytes:
    """Full-bleed intro/outro card in the client's colours."""
    from io import BytesIO

    from PIL import Image, ImageDraw

    from app.services.video import _font, _rgba

    card = Image.new("RGB", (WIDTH, HEIGHT), _rgba(colours.get("bg", "#0B0D12"))[:3])
    draw = ImageDraw.Draw(card)
    accent = _rgba(colours.get("accent", "#C9A227"))[:3]
    text_colour = _rgba(colours.get("text", "#F5F7FA"))[:3]

    cursor = HEIGHT // 2 - 260
    if logo:
        try:
            mark = Image.open(BytesIO(logo)).convert("RGBA")
            mark.thumbnail((460, 460))
            card.paste(mark, ((WIDTH - mark.width) // 2, cursor), mark)
            cursor += mark.height + 70
        except Exception:  # a broken logo must not lose the card
            log.warning("brand_card_logo_unreadable")

    if title:
        font = _font(78, bold=True)
        width = draw.textlength(title, font=font)
        draw.text(((WIDTH - width) / 2, cursor), title, font=font, fill=text_colour)
        cursor += 120
        draw.rectangle([(WIDTH / 2 - 90, cursor), (WIDTH / 2 + 90, cursor + 8)], fill=accent)
        cursor += 70

    body_font = _font(46, bold=False)
    for line in lines:
        if not line:
            continue
        width = draw.textlength(line, font=body_font)
        draw.text(((WIDTH - width) / 2, cursor), line, font=body_font, fill=text_colour)
        cursor += 76

    buffer = BytesIO()
    card.save(buffer, format="PNG")
    return buffer.getvalue()


def _watermark(logo: bytes | None) -> bytes | None:
    """Small semi-transparent corner mark."""
    from io import BytesIO

    from PIL import Image

    if not logo:
        return None
    try:
        mark = Image.open(BytesIO(logo)).convert("RGBA")
    except Exception:
        return None
    mark.thumbnail((150, 150))
    faded = Image.new("RGBA", mark.size, (0, 0, 0, 0))
    for x in range(mark.width):
        for y in range(mark.height):
            r, g, b, a = mark.getpixel((x, y))
            faded.putpixel((x, y), (r, g, b, int(a * 0.72)))
    buffer = BytesIO()
    faded.save(buffer, format="PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
async def edit_video(
    source: bytes,
    *,
    colours: dict[str, str],
    logo: bytes | None = None,
    business_name: str = "",
    contact: str = "",
    settings_: EditSettings | None = None,
    language: str = "uz",
) -> tuple[bytes, bytes | None, EditReport]:
    """Run the whole edit. Returns ``(mp4, poster_jpg, report)``.

    Individual stages fail soft: a missing transcript, an unusable logo or a
    music failure is recorded in the report and the edit continues.
    """
    options = settings_ or EditSettings()
    report = EditReport()
    _binary()  # fail early and clearly when ffmpeg is absent

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        raw = work / "source.mp4"
        raw.write_bytes(source)

        info = await probe(raw)
        report.source_seconds = round(info.duration, 2)

        segments: list[tuple[float, float]] = []
        if options.trim_silence and info.has_audio:
            try:
                segments = keep_segments(info.duration, await detect_silences(raw))
            except PublishError as exc:
                report.skip("trim", str(exc)[:80])
            if segments:
                kept = sum(end - start for start, end in segments)
                report.trimmed_seconds = round(max(0.0, info.duration - kept), 2)
            else:
                report.skip("trim", "nothing worth cutting")
        if not info.has_audio:
            report.skip("audio", "the footage has no sound")

        current = work / "body.mp4"
        # Loudness is measured before anything is applied: one known gain lands
        # on the target, where a single blind pass only gets close.
        measured = (
            await measure_loudness(raw) if (options.clean_audio and info.has_audio) else None
        )
        await normalise(raw, current, info, options, segments, report, measured)

        # ---- subtitles ------------------------------------------------- #
        if options.subtitles and info.has_audio:
            audio_path = work / "speech.m4a"
            if await extract_audio(current, audio_path):
                try:
                    from app.services.transcription import get_transcriber

                    spoken = await get_transcriber().transcribe_segments(
                        audio_path.read_bytes(), filename="speech.m4a", language=language
                    )
                except (ProviderError, ConfigurationError) as exc:
                    spoken = []
                    report.skip("subtitles", str(exc)[:80])
                if spoken:
                    spoken = await correct_transcript(spoken, language)
                    ass_path = work / "subs.ass"
                    ass_path.write_text(
                        build_ass(spoken, colours, karaoke=options.karaoke), encoding="utf-8"
                    )
                    subtitled = work / "subtitled.mp4"
                    try:
                        await burn_subtitles(current, subtitled, ass_path)
                        current = subtitled
                        report.subtitle_lines = len(spoken)
                        report.done("subtitles")
                    except PublishError as exc:
                        report.skip("subtitles", str(exc)[:80])
                else:
                    report.skip("subtitles", "no speech recognised")
            else:
                report.skip("subtitles", "could not extract the audio")

        # ---- music bed --------------------------------------------------- #
        if options.music:
            try:
                music_path = work / "bed.wav"
                _write_music(music_path, await _current_duration(current))
                mixed = work / "mixed.mp4"
                await add_music(current, mixed, music_path, speech=info.has_audio)
                current = mixed
                report.done("music")
            except (PublishError, OSError, ValueError) as exc:
                report.skip("music", str(exc)[:80])

        # ---- brand frames ------------------------------------------------ #
        if options.brand_frames:
            try:
                intro = work / "intro.png"
                intro.write_bytes(_brand_card(colours, logo, title=business_name))
                outro = work / "outro.png"
                outro.write_bytes(
                    _brand_card(colours, logo, title=business_name, lines=(contact,) if contact else ())
                )
                mark_bytes = _watermark(logo)
                mark = None
                if mark_bytes:
                    mark = work / "mark.png"
                    mark.write_bytes(mark_bytes)

                branded = work / "final.mp4"
                await add_brand_frames(current, branded, intro, outro, mark)
                current = branded
                report.done("brand frames")
            except (PublishError, OSError) as exc:
                report.skip("brand frames", str(exc)[:80])

        final = await probe(current)
        report.final_seconds = round(final.duration, 2)

        poster = await _poster(current, work / "poster.jpg")
        log.info(
            "video_edited",
            source=report.source_seconds,
            final=report.final_seconds,
            stages=report.stages,
            skipped=report.skipped,
        )
        return current.read_bytes(), poster, report


async def _current_duration(path: Path) -> float:
    return (await probe(path)).duration


def _write_music(path: Path, seconds: float) -> None:
    """Procedural bed from app/services/music.py — no licensing, no download.

    `render_bed` hands back floats in roughly [-1, 1]; a wav file wants signed
    16-bit, so the samples are scaled on the way out.
    """
    import struct
    import wave

    from app.services.music import SAMPLE_RATE, MusicSpec, render_bed

    samples = render_bed(MusicSpec(seconds=max(4.0, seconds + 1.0), energy="calm"))
    frames = bytearray()
    for value in samples:
        frames += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32000))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames))


async def _poster(video: Path, target: Path) -> bytes | None:
    """A frame from just after the intro, used as the review thumbnail."""
    try:
        await _run(
            [
                _binary(), "-y", "-hide_banner", "-ss", "1.6", "-i", str(video),
                "-frames:v", "1", "-q:v", "3", str(target),
            ],
            stage="poster",
        )
    except PublishError:
        return None
    return target.read_bytes() if target.exists() else None
