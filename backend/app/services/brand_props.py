"""3D prop renders — the objects a kinetic scene is built around.

A clip made only of type is a caption with a background. The reference work
this system is measured against always puts one rendered object on screen and
lets the words sit around it, so every business gets a small library of them
generated once and reused for the life of the account.

These are deliberately *not* photographs, and they live on a separate shelf
from :mod:`app.services.brand_assets`'s photo library, because the two are
composited in opposite ways — see ``_prop_render`` in
:mod:`app.services.kinetic`. Everything here renders a bright object on a pure
black backing so the renderer can drop that backing out.

Generation is best-effort: a business with no props renders exactly as it did
before, so a provider outage during onboarding costs quality, never a signup.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

from app.core.logging import get_logger
from app.services.brand_assets import IMAGE_SUFFIXES, business_dir, shelf_for
from app.services.http import get_client
from app.services.image_gen import ImageGenerator

log = get_logger(__name__)

#: Objects that carry a lesson-shaped idea. Chosen so a strategist writing
#: about almost any education topic finds something that fits: a lock for a
#: plateau, a target for a goal, steps for progress, bubbles for speaking.
BASE_CONCEPTS: tuple[str, ...] = (
    "a closed padlock",
    "a human brain with mechanical gears turning inside it",
    "three stacked speech bubbles arranged diagonally",
    "three ascending platform steps with a sleek arrow rising above them",
    "a dartboard target with a single dart in the exact bullseye",
    "an open book with its pages mid-turn",
    "a graduation cap",
    "an hourglass with the sand running through",
)

#: Shelf-specific objects, appended ahead of the base set for that topic.
SHELF_CONCEPTS: dict[str, tuple[str, ...]] = {
    "it": (
        "a floating terminal window with a blinking cursor",
        "a stack of server blades",
        "a cluster of connected network nodes",
        "a microchip with light tracing through its circuits",
    ),
}

#: The whole point is an object that can be screened onto a dark scene, so the
#: black backing and the absence of a floor or horizon are load-bearing.
PROMPT = (
    "Photorealistic 3D render of {concept}, polished chrome and frosted glass "
    "material with {accent} glowing edges and soft rim light, floating in "
    "empty space, isolated on a pure black background, studio product "
    "lighting, octane render, ultra sharp, high contrast, centred composition"
)

NEGATIVE = (
    "text, letters, words, numbers, watermark, logo, white background, "
    "grey background, floor, table, horizon, room, people, hands, clutter"
)

#: Enough for a clip to never repeat an object twice in a row, few enough that
#: onboarding is not a long wait behind an image provider.
DEFAULT_COUNT = 6

#: Concurrent generations. Providers rate-limit, and onboarding is not a race.
_CONCURRENCY = 3


def props_dir(business_id: uuid.UUID | str) -> Path:
    return business_dir(business_id) / "props"


def _slug(concept: str) -> str:
    """Stable filename per concept, so a re-run tops up instead of duplicating."""
    words = re.sub(r"[^a-z0-9]+", "-", concept.lower()).strip("-").split("-")
    return "-".join(words[:4])[:48]


def concepts_for(topic: str, count: int) -> list[str]:
    shelf = shelf_for(topic)
    ordered = list(SHELF_CONCEPTS.get(shelf, ())) + list(BASE_CONCEPTS)
    return ordered[:count]


def existing(business_id: uuid.UUID | str) -> list[Path]:
    folder = props_dir(business_id)
    try:
        return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    except OSError:
        return []


async def _render_one(
    generator: ImageGenerator, concept: str, accent: str, target: Path
) -> Path | None:
    try:
        image = await generator.generate(
            PROMPT.format(concept=concept, accent=accent),
            aspect_ratio="1:1",
            negative_prompt=NEGATIVE,
            store=False,
        )
        client = await get_client("download", timeout=120)
        response = await client.get(image.url)
        if not response.is_success:
            raise OSError(f"HTTP {response.status_code}")
        target.write_bytes(response.content)
    except Exception as exc:                      # never fail onboarding over a prop
        log.warning("brand_prop_failed", concept=concept, error=str(exc))
        return None
    log.info("brand_prop_rendered", concept=concept, file=target.name)
    return target


async def ensure_props(
    business_id: uuid.UUID | str,
    *,
    accent: str = "#37B3A2",
    topic: str = "",
    count: int = DEFAULT_COUNT,
    generator: ImageGenerator | None = None,
) -> list[Path]:
    """Fill this business's prop shelf, skipping whatever is already there.

    Safe to call more than once: filenames come from the concept, so a second
    run tops the shelf up rather than doubling it. Returns everything on the
    shelf afterwards, including props from earlier runs.
    """
    generator = generator or ImageGenerator()
    if not generator.enabled:
        log.info("brand_props_skipped", reason="image provider not configured")
        return existing(business_id)

    folder = props_dir(business_id)
    folder.mkdir(parents=True, exist_ok=True)
    missing = [
        (concept, folder / f"{_slug(concept)}.png")
        for concept in concepts_for(topic, count)
        if not (folder / f"{_slug(concept)}.png").exists()
    ]
    if not missing:
        return existing(business_id)

    limit = asyncio.Semaphore(_CONCURRENCY)

    async def guarded(concept: str, target: Path) -> Path | None:
        async with limit:
            return await _render_one(generator, concept, accent, target)

    results = await asyncio.gather(*(guarded(c, t) for c, t in missing))
    log.info(
        "brand_props_filled",
        business=str(business_id),
        requested=len(missing),
        rendered=sum(1 for r in results if r is not None),
    )
    return existing(business_id)
