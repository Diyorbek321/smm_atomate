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

        try:
            plan = await self.ask_json(
                prompt, EditPlan, system=system, temperature=0.3, max_tokens=1600
            )
        except Exception as exc:
            log.warning("video_edit_plan_failed", error=str(exc)[:200])
            return EditPlan(keep=[], subtitle_style="none")

        return self._sanitise(plan, request.duration)

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
    def _sanitise(plan: EditPlan, duration: float) -> EditPlan:
        """Clamp the plan to timestamps that exist and a length that publishes.

        Models routinely return an ``end`` past the file, reversed pairs, and
        overlapping segments — each of which makes ffmpeg either fail or emit a
        clip with a chunk repeated in the middle.
        """
        limit = duration if duration > 0 else MAX_CLIP_SECONDS
        cleaned: list[KeepSegment] = []
        for segment in plan.keep:
            start = max(0.0, min(segment.start, limit))
            end = max(0.0, min(segment.end, limit))
            if end - start < MIN_SEGMENT_SECONDS:
                continue
            cleaned.append(KeepSegment(start=round(start, 2), end=round(end, 2), why=segment.why[:120]))

        cleaned.sort(key=lambda s: s.start)

        # Overlaps would duplicate speech in the output; the later segment yields.
        merged: list[KeepSegment] = []
        for segment in cleaned:
            if merged and segment.start < merged[-1].end:
                segment = KeepSegment(start=merged[-1].end, end=segment.end, why=segment.why)
                if segment.duration < MIN_SEGMENT_SECONDS:
                    continue
            merged.append(segment)

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

        style = plan.subtitle_style.strip().lower()
        if style not in SUBTITLE_STYLES:
            style = "full"

        hook = plan.hook_at
        if hook is not None and not (0.0 <= hook <= limit):
            hook = None

        return EditPlan(
            keep=kept,
            hook_at=hook,
            drop=[d.strip() for d in plan.drop if d.strip()][:8],
            subtitle_style=style,
            title=plan.title.strip()[:60],
        )
