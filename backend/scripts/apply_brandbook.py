#!/usr/bin/env python
"""Push a brandbook file into the knowledge base it describes.

    python scripts/apply_brandbook.py <brandbook.json> --business <slug>
    python scripts/apply_brandbook.py <brandbook.json> --business <slug> --write

The brandbook is the document a human edits; the knowledge base is the subset
a machine reads. Keeping two copies in sync by hand works exactly until
somebody changes one of them, so this makes the direction explicit: the file
is the source, the database is derived, and nothing flows back.

Two rules keep it safe to run against a live client:

* It touches brand fields only. Prices, offerings, FAQ and notes belong to the
  knowledge base and are never overwritten from here — a brandbook that says
  nothing about prices must not erase them.
* It prints the change and stops. `--write` is required to commit, because the
  first thing anyone does with a script like this is run it on the wrong slug.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import configure_logging
from app.db.session import session_scope
from app.repositories.business import (
    BusinessRepository,
    KnowledgeBaseRepository,
)
from app.services.brand_kit import AVAILABLE_FONTS

#: The brandbook names colours by their role in the design; the renderer names
#: them by their role in a card. Neither vocabulary is wrong, so the mapping
#: lives here rather than forcing one side to speak the other's language.
COLOR_MAP = {
    "bg": "bg",
    "deep": "surface",
    "ink": "text",
    "brand": "primary",
    "accent": "accent",
}

#: Five clauses appended to every image prompt — see app/services/style_dna.py.
STYLE_FIELDS = ("palette", "lighting", "lens", "grade", "subject")


def _hex(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text.startswith("#") and len(text) == 7 else None


def colors_from(book: dict[str, Any]) -> dict[str, str]:
    palette = book.get("palette") or {}
    colors = {
        target: value
        for source, target in COLOR_MAP.items()
        if (value := _hex(palette.get(source)))
    }
    # What sits ON the accent — a pill's label, a highlighted number. The
    # brandbook rarely states it because a designer just knows; the field
    # colour is the answer in every palette built this way.
    explicit = _hex(palette.get("on_accent"))
    if explicit or colors.get("bg"):
        colors["on_accent"] = explicit or colors["bg"]
    return colors


def style_from(book: dict[str, Any]) -> dict[str, str]:
    style = book.get("visual_style") or {}
    return {
        field: str(style[field]).strip()
        for field in STYLE_FIELDS
        if isinstance(style.get(field), str) and style[field].strip()
    }


def kit_from(book: dict[str, Any], warn: list[str]) -> dict[str, Any]:
    typography = book.get("typography") or {}
    voice = book.get("voice") or {}
    logo = book.get("logo") or {}

    fonts: dict[str, str] = {}
    for role, key in (("display", "display"), ("body", "body")):
        name = str(typography.get(key, "")).strip()
        if not name:
            continue
        if name not in AVAILABLE_FONTS:
            warn.append(f"shrift '{name}' o'rnatilmagan — o'tkazib yuborildi ({role})")
            continue
        fonts[role] = name

    kit: dict[str, Any] = {}
    if fonts:
        kit["typography"] = fonts

    voice_out = {
        "summary": str(voice.get("in_one_line", "")).strip(),
        "do": [str(x).strip() for x in (voice.get("do") or []) if str(x).strip()],
        "dont": [str(x).strip() for x in (voice.get("dont") or []) if str(x).strip()],
        "banned_words": [
            str(x).strip() for x in (voice.get("banned_words") or []) if str(x).strip()
        ],
    }
    if any(voice_out.values()):
        kit["voice"] = voice_out

    for source, target in (("avatar", "logo_on_dark"), ("on_light", "logo_on_light")):
        path = str(logo.get(source, "")).strip()
        if path:
            kit[target] = path
    return kit


def contacts_from(book: dict[str, Any]) -> dict[str, str]:
    channels = book.get("channels") or {}
    contact = book.get("contact") or {}
    out: dict[str, str] = {}
    if handle := str(channels.get("contact", "")).strip().lstrip("@"):
        out["telegram_username"] = handle
    if insta := str(channels.get("instagram", "")).strip().lstrip("@"):
        out["instagram_username"] = insta
    if phone := str(contact.get("phone", "")).strip():
        out["phone"] = phone
    return out


def _show(label: str, before: Any, after: Any) -> bool:
    """Print one field's change; return whether anything actually moved."""
    if before == after:
        return False
    print(f"  {label}")
    print(f"      eski : {json.dumps(before, ensure_ascii=False)[:110]}")
    print(f"      yangi: {json.dumps(after, ensure_ascii=False)[:110]}")
    return True


async def apply(path: Path, slug: str, *, write: bool) -> None:
    book = json.loads(path.read_text(encoding="utf-8"))
    warn: list[str] = []

    colors = colors_from(book)
    style = style_from(book)
    kit = kit_from(book, warn)
    contacts = contacts_from(book)

    async with session_scope() as session:
        business = await BusinessRepository(session).by_slug(slug)
        if business is None:
            raise SystemExit(f"'{slug}' topilmadi")
        knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)

        print(f"{book.get('name', path.stem)} → {business.name} ({slug})\n")
        changed = False
        if colors:
            changed |= _show("brand_colors", knowledge.brand_colors, colors)
        if style:
            changed |= _show("visual_style", knowledge.visual_style, style)
        if kit:
            changed |= _show("brand_kit", knowledge.brand_kit, kit)
        for field, value in contacts.items():
            changed |= _show(field, getattr(knowledge, field, None), value)

        for line in warn:
            print(f"  ⚠ {line}")

        if not changed:
            print("  o'zgarish yo'q — baza brandbook bilan bir xil")
            return

        if not write:
            print("\nQo'llash uchun: --write")
            return

        # Brand fields only. Prices, offerings and FAQ belong to the knowledge
        # base; a brandbook that is silent about them must not erase them.
        if colors:
            knowledge.brand_colors = colors
        if style:
            knowledge.visual_style = style
        if kit:
            knowledge.brand_kit = kit
        for field, value in contacts.items():
            setattr(knowledge, field, value)
        knowledge.compute_completeness()
        await session.flush()
        print(f"\n✅ qo'llandi — to'liqlik {knowledge.completeness_score:.0%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Brandbook faylini bilim bazasiga ko'chiradi")
    parser.add_argument("brandbook", type=Path)
    parser.add_argument("--business", required=True, help="biznes slug'i, masalan postchi")
    parser.add_argument("--write", action="store_true", help="haqiqatan yozish")
    args = parser.parse_args()

    configure_logging("apply-brandbook")
    asyncio.run(apply(args.brandbook, args.business, write=args.write))


if __name__ == "__main__":
    main()
