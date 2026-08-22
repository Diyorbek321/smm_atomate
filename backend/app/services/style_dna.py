"""The look every generated photo for one business has to share.

A diffusion model answers each prompt on its own terms. Ask it for twenty
photos across twenty topics and you get twenty unrelated pictures — correct
one at a time, a stock collage once they sit in a feed together. What makes a
feed read as *designed* is not the subject of any single image but the things
that stay constant between them: the palette, where the light comes from, the
lens, the grade, and who is in frame.

So those five are pinned per business and appended to every prompt. They are
stored on the knowledge base (`visual_style`) and can be edited like any other
brand fact; when nothing is stored, one is derived from the brand colours so a
new client still gets a consistent feed on day one.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.models.enums import BusinessCategory

log = get_logger(__name__)

#: Kept short on purpose. Every clause here competes with the sentence that
#: describes the actual subject, and a prompt that is nine-tenths style
#: instruction stops depicting anything in particular.
MAX_CLAUSE = 90


class StyleDNA(BaseModel):
    """Five constants, appended to every image prompt for one business."""

    palette: str = Field(default="", description="Ranglar, masalan 'charcoal and gold'")
    lighting: str = Field(default="", description="Yorug'lik xarakteri")
    lens: str = Field(default="", description="Obyektiv va chuqurlik")
    grade: str = Field(default="", description="Rang berish, kayfiyat")
    subject: str = Field(default="", description="Kadrdagi odamlar va muhit")

    def clauses(self) -> list[str]:
        return [
            clause.strip()[:MAX_CLAUSE]
            for clause in (self.subject, self.lighting, self.lens, self.palette, self.grade)
            if clause and clause.strip()
        ]

    def suffix(self) -> str:
        return ", ".join(self.clauses())


#: House defaults, written the way a photographer briefs a shoot rather than
#: the way a model is usually prompted — concrete, and repeatable across
#: subjects.
BASE_STYLE = StyleDNA(
    lighting="soft directional daylight, warm highlights, gentle falloff",
    lens="50mm, eye level, shallow depth of field",
    grade="clean filmic grade, natural skin tones, fine grain",
)

#: What belongs in frame differs by trade; the rest of the DNA does not.
SUBJECT_BY_CATEGORY: dict[BusinessCategory, str] = {
    BusinessCategory.EDUCATION: (
        "real Uzbek students and teachers in a bright modern classroom, candid, unposed"
    ),
    BusinessCategory.BEAUTY: "a calm modern salon interior, real hands at work, close detail",
    BusinessCategory.FOOD_BEVERAGE: "fresh food on a simple table, natural light, no plastic props",
    BusinessCategory.ECOMMERCE: "the product in real use at home, uncluttered, honest scale",
    BusinessCategory.RETAIL: "a tidy shop interior, products in real use, uncluttered shelves",
    BusinessCategory.TECH: "a real desk mid-work, screens and hands, no glowing abstractions",
    BusinessCategory.HEALTHCARE: "a clean bright clinic, calm and professional, no stock smiles",
    BusinessCategory.REAL_ESTATE: "a real room shot wide, daylight through the windows, lived in",
}
DEFAULT_SUBJECT = "a real local workplace, documentary framing, unposed people"


def _palette_clause(brand_colors: dict[str, Any] | None) -> str:
    """Name the brand's own colours so the model paints with them."""
    colors = brand_colors or {}
    picked = [
        str(colors[key]) for key in ("bg", "accent", "text") if isinstance(colors.get(key), str)
    ]
    hexes = [value for value in picked if value.startswith("#") and len(value) == 7]
    if not hexes:
        return ""
    return "colour palette built from " + " and ".join(hexes[:2])


def style_for(
    category: BusinessCategory | str | None,
    brand_colors: dict[str, Any] | None = None,
    stored: dict[str, Any] | None = None,
) -> StyleDNA:
    """The business's style: what is stored, over a derived default.

    Every field falls back independently, so an owner who only wants to pin the
    lighting keeps sensible values for the rest.
    """
    try:
        chosen = BusinessCategory(category) if category else None
    except ValueError:
        chosen = None

    derived = BASE_STYLE.model_copy(
        update={
            "subject": SUBJECT_BY_CATEGORY.get(chosen, DEFAULT_SUBJECT) if chosen else DEFAULT_SUBJECT,
            "palette": _palette_clause(brand_colors),
        }
    )
    if not stored:
        return derived

    overrides = {
        # Capped here rather than only at render time, so an over-long clause
        # cannot sit in the object waiting to surprise a later caller.
        key: str(value).strip()[:MAX_CLAUSE]
        for key, value in stored.items()
        if key in StyleDNA.model_fields and isinstance(value, str) and value.strip()
    }
    return derived.model_copy(update=overrides)


def apply_style(prompt: str, style: StyleDNA) -> str:
    """Append the constants to a prompt that describes one specific subject."""
    suffix = style.suffix()
    if not prompt.strip():
        return suffix
    if not suffix:
        return prompt
    return f"{prompt.rstrip('. ')}. {suffix}."
