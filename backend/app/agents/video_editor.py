"""VideoEditorAgent — decides the cut; ffmpeg performs it.

:mod:`app.services.video_editor` is entirely deterministic: it detects silence,
inverts it into segments worth keeping, and stitches them back together. That
removes dead air, which is the mechanical half of editing. It has no way to
notice that the owner said the same thing twice, wandered off the topic for
fifteen seconds, or buried the strongest line at the very end.

This agent reads the transcript and makes those calls, returning an edit plan
the service can execute. It never touches the file.

The plan is advisory: when the agent is unavailable or the transcript is empty,
``EditPlan.is_usable`` is False and the caller keeps the silence-trim behaviour
it had before.

:meth:`_sanitise` has always repaired what a model gets wrong — reversed pairs,
overlaps, timestamps past the end of the file, a plan longer than the format
allows. What it did not do was *say so*. A plan that arrived needing six of its
eight segments thrown away was silently reduced to two and shipped, and the
edit that reached the owner was the repair rather than anything anyone chose.

So the repair now reports what it had to do, and a plan that needed too much of
it is sent back with the reasons attached. The last attempt ships whatever it
has: an over-repaired edit is a worse clip, and no clip at all is worse still.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.agents.prompts import VIDEO_EDITOR_SYSTEM
from app.core.logging import get_logger
from app.models.business import Business

log = get_logger(__name__)

#: Reels and Shorts stop being watched past this; the prompt is told to cut to it.
MAX_CLIP_SECONDS = 60.0
#: Shorter than this is a frame, not a segment — usually a mis-parsed timestamp.
MIN_SEGMENT_SECONDS = 0.8

#: Rewrites allowed before the repaired plan is shipped as-is.
ATTEMPTS = 2

#: How much of a plan may be repaired before it stops being the model's plan.
#: Losing a segment to an overlap is ordinary; losing half of them means the
#: model did not understand the transcript, and repairing that produces an edit
#: nobody designed.
MAX_REPAIRED = 0.4

#: An "edit" that keeps one unbroken run of the source has not edited anything.
#: Usually the model echoing the whole duration back rather than choosing.
UNCUT_RATIO = 0.95
SUBTITLE_STYLES = frozenset({"full", "keyword", "none"})


class KeepSegment(BaseModel):
    start: float = Field(default=0.0, ge=0.0)
    end: float = Field(default=0.0, ge=0.0)
    why: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class EditPlan(BaseModel):
    """What to keep, what to drop, and how to caption it."""

    keep: list[KeepSegment] = Field(default_factory=list)
    hook_at: float | None = Field(default=None, description="Eng kuchli 3 soniya qayerdan boshlanadi")
    drop: list[str] = Field(default_factory=list, description="Nima olib tashlandi va nega")
    subtitle_style: str = "full"
    title: str = ""

    @property
    def total_seconds(self) -> float:
        return round(sum(segment.duration for segment in self.keep), 2)

    @property
    def is_usable(self) -> bool:
        return bool(self.keep) and self.total_seconds >= MIN_SEGMENT_SECONDS


@dataclass(slots=True)
class VideoEditRequest:
    business: Business
    #: Whisper segments: ``[{"start": float, "end": float, "text": str}, ...]``
    segments: list[dict[str, Any]] = field(default_factory=list)
    duration: float = 0.0
    topic: str = ""


class VideoEditorAgent(BaseAgent):
    name = "video_editor"

    async def run(self, request: VideoEditRequest) -> EditPlan:
        transcript = self._transcript_block(request.segments)
        if not transcript:
            # Nothing to reason about — the caller falls back to silence-trim.
            log.info("video_edit_no_transcript", business=str(request.business.id))
            return EditPlan(keep=[], subtitle_style="none")

        system = await self.system_prompt(VIDEO_EDITOR_SYSTEM, business_id=request.business.id)
        prompt = "\n\n".join(
            filter(
                None,
                [
                    f"BREND: {request.business.name}",
                    f"MAVZU: {request.topic}" if request.topic else "",
                    f"VIDEO DAVOMIYLIGI: {request.duration:.1f} soniya",
                    f"TRANSKRIPT (vaqt belgilari bilan):\n{transcript}",
                    f"Montaj rejasini JSON qaytar. Yakuniy davomiylik {MAX_CLIP_SECONDS:.0f} soniyadan oshmasin.",
                ],
            )
        )

        complaints: list[str] = []
        repaired = EditPlan(keep=[], subtitle_style="none")
        for attempt in range(ATTEMPTS):
            try:
                plan = await self.ask_json(
                    (prompt if not complaints else
                     f"{prompt}\n\nOLDINGI URINISH XATOSI: {'; '.join(complaints[:4])}"
                     "\nShu xatolarni takrorlama."),
                    EditPlan, system=system,
                    temperature=0.3 if attempt == 0 else 0.15,
                    max_tokens=1600,
                )
            except Exception as exc:
                log.warning("video_edit_plan_failed", attempt=attempt + 1,
                            error=str(exc)[:200])
                return repaired

            repaired, complaints = self._sanitise(plan, request.duration)
            if not complaints or attempt == ATTEMPTS - 1:
                log.info("video_edit_planned", attempt=attempt + 1,
                         kept=len(repaired.keep), seconds=repaired.total_seconds,
                         repaired=len(complaints))
                return repaired
            log.info("video_edit_replanning", attempt=attempt + 1,
                     reasons=complaints[:3])
        return repaired

    # ------------------------------------------------------------------ #
    @staticmethod
    def _transcript_block(segments: list[dict[str, Any]], limit: int = 120) -> str:
        lines = []
        for segment in segments[:limit]:
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            try:
                start = float(segment.get("start", 0.0))
                end = float(segment.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            lines.append(f"[{start:.1f}-{end:.1f}] {text}")
        return "\n".join(lines)

    @staticmethod
    def _sanitise(plan: EditPlan, duration: float) -> tuple[EditPlan, list[str]]:
        """Clamp the plan, and say what had to be clamped.

        Models routinely return an ``end`` past the file, reversed pairs, and
        overlapping segments — each of which makes ffmpeg either fail or emit a
        clip with a chunk repeated in the middle. Repairing them is not
        optional. Repairing them *quietly* is what made a heavily-wrong plan
        indistinguishable from a good one, so the second return value carries
        the reasons, in Uzbek, ready to go back to the model.
        """
        limit = duration if duration > 0 else MAX_CLIP_SECONDS
        complaints: list[str] = []
        asked = len(plan.keep)
        cleaned: list[KeepSegment] = []
        for segment in plan.keep:
            start = max(0.0, min(segment.start, limit))
            end = max(0.0, min(segment.end, limit))
            if end - start < MIN_SEGMENT_SECONDS:
                continue
            cleaned.append(KeepSegment(start=round(start, 2), end=round(end, 2), why=segment.why[:120]))

        if len(cleaned) < asked:
            complaints.append(
                f"{asked - len(cleaned)} ta bo'lak fayl chegarasidan tashqarida "
                f"yoki juda qisqa edi (video {limit:.1f} soniya)")

        ordered = sorted(cleaned, key=lambda s: s.start)
        if [s.start for s in ordered] != [s.start for s in cleaned]:
            complaints.append("bo'laklar vaqt tartibida emas edi")
        cleaned = ordered

        # Overlaps would duplicate speech in the output; the later segment yields.
        merged: list[KeepSegment] = []
        overlaps = 0
        for segment in cleaned:
            if merged and segment.start < merged[-1].end:
                overlaps += 1
                segment = KeepSegment(start=merged[-1].end, end=segment.end, why=segment.why)
                if segment.duration < MIN_SEGMENT_SECONDS:
                    continue
            merged.append(segment)
        if overlaps:
            complaints.append(
                f"{overlaps} ta bo'lak bir-birining ustiga tushdi — bir gap "
                "klipda ikki marta chiqadi")

        # Trim from the end until it fits: the tail is where the weakest
        # material sits once the hook has been moved to the front.
        kept: list[KeepSegment] = []
        running = 0.0
        for segment in merged:
            if running + segment.duration > MAX_CLIP_SECONDS:
                remaining = MAX_CLIP_SECONDS - running
                if remaining >= MIN_SEGMENT_SECONDS:
                    kept.append(
                        KeepSegment(
                            start=segment.start,
                            end=round(segment.start + remaining, 2),
                            why=segment.why,
                        )
                    )
                break
            kept.append(segment)
            running += segment.duration
        if len(kept) < len(merged):
            complaints.append(
                f"reja {MAX_CLIP_SECONDS:.0f} soniyadan uzun edi, oxiri kesildi")

        style = plan.subtitle_style.strip().lower()
        if style not in SUBTITLE_STYLES:
            style = "full"

        # A hook has to point at material that survived. Range-checking it
        # against the file was never enough: a hook aimed into a segment the
        # plan itself dropped is a hook at nothing.
        hook = plan.hook_at
        if hook is not None:
            inside = any(s.start <= hook <= s.end for s in kept)
            if not (0.0 <= hook <= limit) or not inside:
                complaints.append(
                    "«hook_at» saqlanadigan bo'lakning ichida emas")
                hook = None

        repaired = EditPlan(
            keep=kept,
            hook_at=hook,
            drop=[d.strip() for d in plan.drop if d.strip()][:8],
            subtitle_style=style,
            title=plan.title.strip()[:60],
        )

        if not kept:
            complaints.append("birorta ham yaroqli bo'lak qolmadi")
        elif asked and (asked - len(kept)) / asked > MAX_REPAIRED:
            complaints.append(
                f"{asked} ta bo'lakdan {len(kept)} tasi qoldi — reja "
                "transkriptga mos kelmadi")
        elif len(kept) == 1 and limit and kept[0].duration / limit > UNCUT_RATIO:
            # Not a repair, a judgement: the model handed the whole file back.
            complaints.append(
                "butun video bitta bo'lak sifatida qaytarildi — bu montaj emas; "
                "takrorlarni, mavzudan chetga chiqishni va bo'sh joylarni olib tashla")

        return repaired, complaints
