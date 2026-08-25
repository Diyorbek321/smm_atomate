"""ScoutAgent — reads the neighbourhood and reports what is working in it.

:mod:`app.services.telegram_scout` fetches competitor channels and ranks their
posts by how far each one beat its own channel's median. That ranking is a list
of numbers. This agent says what the numbers mean: which themes are earning
attention, which format carries them, what nobody in the niche is covering, and
what everyone just did.

Two guardrails, because the failure modes here are specific and both are worse
than having no scout at all:

* **It must not hand back a competitor's sentence.** A theme is "graduates
  posting their own certificate"; a sentence is somebody's copy. The prompt
  says so and :func:`_drop_copied` enforces it against the source corpus,
  because a client publishing a rival's line is the one outcome that would
  actually cost them something.
* **It must not invent a trend from one post.** A single channel is one
  opinion; the report says how many channels a theme showed up in, and code
  holds the confidence down when that number is one.

The output reaches the strategist the same way the analyst's does — through the
marketolog's brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent, knowledge_context
from app.agents.prompts import SCOUT_SYSTEM
from app.core.logging import get_logger
from app.models.business import Business
from app.models.knowledge_base import KnowledgeBase
from app.services.telegram_scout import ChannelSnapshot
from app.utils.similarity import DUPLICATE_THRESHOLD, similarity

log = get_logger(__name__)

#: How much of a post the model is shown. Enough to recognise the subject,
#: too little to lift as copy — the truncation is a guardrail, not a saving.
POST_PREVIEW_CHARS = 180
#: A theme seen on one channel is that channel's habit, not the niche's.
MIN_CHANNELS_FOR_TREND = 2


class TrendTheme(BaseModel):
    """One subject that is earning attention next door."""

    topic: str = Field(default="", description="Mavzu — GAP EMAS, mavzu nomi")
    why: str = Field(default="", description="Nega ishlayapti deb o'ylaysan")
    channels: int = Field(default=1, ge=0, description="Nechta kanalda uchradi")


class TrendReport(BaseModel):
    themes: list[TrendTheme] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list, description="Qaysi format ko'proq ko'rilgan")
    gaps: list[str] = Field(default_factory=list, description="Hech kim yopmagan mavzu — bizning ochiq joyimiz")
    saturated: list[str] = Field(default_factory=list, description="Hamma endi bosgan — takrorlamaymiz")
    note: str = Field(default="", description="Ma'lumot kam bo'lsa shu yerda ayt")

    @property
    def is_usable(self) -> bool:
        return bool(self.themes or self.gaps or self.saturated)

    def as_instructions(self) -> str:
        """Render for the marketolog's brief. Empty sections are dropped."""
        blocks: list[str] = []

        confirmed = [t for t in self.themes if t.channels >= MIN_CHANNELS_FOR_TREND]
        if confirmed:
            rows = "\n".join(
                f"- {t.topic.strip()} ({t.channels} kanalda)"
                + (f" — {t.why.strip()}" if t.why.strip() else "")
                for t in confirmed
            )
            blocks.append(f"QO'SHNILARDA ISHLAYAPTI:\n{rows}")

        if self.formats:
            blocks.append("KO'PROQ KO'RILGAN FORMAT: " + ", ".join(self.formats))
        if self.gaps:
            blocks.append(
                "HECH KIM YOPMAGAN (bizning ochiq joyimiz):\n"
                + "\n".join(f"- {g.strip()}" for g in self.gaps)
            )
        if self.saturated:
            blocks.append(
                "QOVUSHGAN — shu hafta TAKRORLAMA: "
                + ", ".join(s.strip() for s in self.saturated)
            )

        if not blocks:
            return ""
        return "RAZVEDKA (ochiq Telegram kanallaridan):\n" + "\n\n".join(blocks)


@dataclass(slots=True)
class ScoutRequest:
    business: Business
    knowledge: KnowledgeBase | None
    snapshots: list[ChannelSnapshot] = field(default_factory=list)
    #: Competitor entries that were names rather than channels — reported back
    #: so the bot can ask the owner for the link.
    unresolved: list[str] = field(default_factory=list)


class ScoutAgent(BaseAgent):
    name = "scout"
    use_pro_model = True

    async def run(self, request: ScoutRequest) -> TrendReport:
        usable = [s for s in request.snapshots if s.is_usable]
        if not usable:
            return TrendReport(
                note="Raqobatchi kanallar o'qilmadi — tahlil qilinadigan ma'lumot yo'q."
            )

        corpus = self._corpus(usable)
        if not corpus.strip():
            return TrendReport(note="Kanallar o'qildi, lekin ajralib chiqqan post yo'q.")

        system = await self.system_prompt(SCOUT_SYSTEM, business_id=request.business.id)
        prompt = "\n\n".join(
            filter(
                None,
                [
                    knowledge_context(request.business, request.knowledge),
                    f"O'QILGAN KANALLAR: {len(usable)} ta",
                    corpus,
                    "Razvedka hisobotini JSON qaytar.",
                ],
            )
        )

        try:
            report = await self.ask_json(
                prompt, TrendReport, system=system, temperature=0.4, max_tokens=1400
            )
        except Exception as exc:
            log.warning("scout_failed", business=str(request.business.id), error=str(exc)[:200])
            return TrendReport(note="Razvedka bajarilmadi.")

        return self._sanitise(report, usable)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _corpus(snapshots: list[ChannelSnapshot]) -> str:
        """The outperformers, shown with the number that made them interesting.

        Lift is included rather than raw views on purpose: the model would
        otherwise rank a big channel's ordinary post above a small one's hit,
        which is the exact mistake the per-channel ranking exists to prevent.
        """
        blocks: list[str] = []
        for snapshot in snapshots:
            rows = [
                f"- [{post.lift}x o'rtachadan, {post.media}, {post.words} so'z] "
                # Flattened: a post's own line breaks would otherwise split one
                # row across several, and the model reads the tail as a
                # separate, unlabelled post.
                f"{' '.join(post.text.split())[:POST_PREVIEW_CHARS]}"
                for post in snapshot.outperformers()
            ]
            if not rows:
                continue
            blocks.append(
                f"@{snapshot.handle} ({snapshot.subscribers or '?'} obunachi, "
                f"o'rtacha {snapshot.median_views} ko'rish):\n" + "\n".join(rows)
            )
        return "\n\n".join(blocks)

    @staticmethod
    def _source_texts(snapshots: list[ChannelSnapshot]) -> list[str]:
        return [post.text for snapshot in snapshots for post in snapshot.posts if post.text]

    @classmethod
    def _sanitise(cls, report: TrendReport, snapshots: list[ChannelSnapshot]) -> TrendReport:
        """Cap the counts to reality and strip anything lifted from a source."""
        sources = cls._source_texts(snapshots)
        channel_count = len(snapshots)

        themes: list[TrendTheme] = []
        for theme in report.themes:
            topic = theme.topic.strip()
            if not topic or _is_copied(topic, sources):
                continue
            themes.append(
                TrendTheme(
                    topic=topic[:120],
                    why=theme.why.strip()[:160],
                    # A model claiming five channels when four were read is
                    # inflating its own evidence.
                    channels=min(theme.channels, channel_count),
                )
            )

        return TrendReport(
            themes=themes[:5],
            formats=[f.strip()[:40] for f in report.formats if f.strip()][:3],
            gaps=_drop_copied(report.gaps, sources)[:4],
            saturated=_drop_copied(report.saturated, sources)[:4],
            note=report.note.strip()[:300],
        )


def _is_copied(candidate: str, sources: list[str]) -> bool:
    """True when this line is somebody else's post wearing a new coat."""
    return any(similarity(candidate, source) >= DUPLICATE_THRESHOLD for source in sources)


def _drop_copied(values: list[str], sources: list[str]) -> list[str]:
    kept: list[str] = []
    for value in values:
        text = value.strip()
        if not text:
            continue
        if _is_copied(text, sources):
            log.info("scout_dropped_copied_line", line=text[:60])
            continue
        kept.append(text[:160])
    return kept
