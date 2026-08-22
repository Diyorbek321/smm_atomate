"""A second pair of eyes on the rendered image, before anyone else sees it.

The editor agent scores the *words*. Nothing scored the picture, so a card with
a headline running off the edge, or a generated photo with mangled lettering in
it, reached the owner's review queue looking exactly as confident as a good one.

This is the cheap version of that check: the finished pixels go back to a
multimodal model with one question — would you publish this? It costs a
fraction of a cent and catches the small share of renders that are visibly
broken. When no multimodal provider is configured the check returns ``None``
and the pipeline carries on unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

QC_SYSTEM = """
Sen — SMM agentligining bosh dizayneri. Senga tayyor post rasmi ko'rsatiladi.
Vazifang: uni mijoz feed'iga qo'yish mumkinmi yoki yo'qligini hal qilish.

QAT'IY TEKSHIR:
1. MATN TO'LIQMI — biror so'z kadr chetidan chiqib ketmaganmi, kesilmaganmi,
   ustma-ust tushmaganmi. Yarim ko'rinayotgan harf — jiddiy nuqson.
2. O'QILADIMI — matn va fon orasida kontrast yetarlimi.
3. RASMDA G'ALATILIK BORMI — buzuq yuz, qo'shimcha barmoq, ma'nosiz
   harflar/yozuvlar, cho'zilgan predmet.
4. TARTIB — logo va aloqa satri joyidami, bo'sh joy muvozanatlimi.

BALL (1-10): 8+ = e'lon qilsa bo'ladi. 5-7 = zaif, lekin halokat emas.
1-4 = nuqsonli, qayta chizilsin.
Nuqsonlarni O'ZBEK tilida, qisqa yoz — har biri bitta jumla.
Nuqson yo'q bo'lsa issues bo'sh qolsin. Bahona va maqtov yozma.
""".strip()


class VisualVerdict(BaseModel):
    """What the reviewer saw."""

    score: int = Field(default=5, ge=1, le=10)
    text_complete: bool = Field(default=True, description="Hech qanday matn kesilmagan")
    readable: bool = Field(default=True, description="Kontrast yetarli")
    issues: list[str] = Field(default_factory=list)

    @property
    def acceptable(self) -> bool:
        """Good enough to publish without another attempt."""
        return (
            self.score >= settings.visual_qc_min_score and self.text_complete and self.readable
        )


async def review_image(
    image: bytes, *, expect_text: str = "", mime_type: str = "image/png"
) -> VisualVerdict | None:
    """Judge one rendered image; ``None`` when the check cannot run.

    Never raises: a quality gate that can break the pipeline is worse than no
    quality gate, so every failure path degrades to "no opinion".
    """
    if not settings.visual_qc or not image:
        return None

    prompt = "Shu rasmni baholab, JSON qaytar."
    if expect_text:
        # Knowing the intended words is what makes "is anything cut off?"
        # answerable — the model can compare what it reads to what was meant.
        prompt = f"Kartada shu matn bo'lishi kerak edi:\n«{expect_text[:300]}»\n\n{prompt}"

    try:
        from app.services.llm import get_document_llm

        verdict, _ = await get_document_llm().generate_structured_document(
            prompt,
            VisualVerdict,
            data=image,
            mime_type=mime_type,
            system=QC_SYSTEM,
            temperature=0.1,
            max_tokens=600,
        )
    except Exception as exc:
        log.info("visual_qc_unavailable", error=str(exc)[:200])
        return None

    log.info(
        "visual_qc",
        score=verdict.score,
        complete=verdict.text_complete,
        issues=len(verdict.issues),
    )
    return verdict
