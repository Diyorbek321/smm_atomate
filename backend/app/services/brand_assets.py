"""Where a business's visual assets live, and the order they are looked up in.

One client's clips should never show another client's imagery, but a new
client should not start with an empty library either. The lookup walks from
the most specific shelf to the shared fallback:

    brand/<business>/photos/<shelf>/  →  brand/<business>/photos/
    brand/photos/<shelf>/             →  brand/photos/
"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.services.storage import get_storage

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")

#: Topic keywords that select a themed shelf, so a clip about code does not
#: open on a photograph of books.
TOPIC_SHELVES: dict[str, tuple[str, ...]] = {
    "it": (
        "it ", " it", "kod", "dastur", "backend", "frontend", "python", "web",
        "sayt", "bot", "kompyuter", "server", "ma'lumotlar bazasi", "developer",
    ),
}


def shelf_for(topic: str) -> str:
    lowered = f" {topic.lower()} "
    for shelf, keywords in TOPIC_SHELVES.items():
        if any(word in lowered for word in keywords):
            return shelf
    return ""


def _images(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    except OSError:
        return []


def business_dir(business_id: uuid.UUID | str) -> Path:
    return get_storage().root / "brand" / str(business_id)


VIDEO_SUFFIXES = (".mp4", ".mov", ".webm")


def footage_library(business_id: uuid.UUID | str | None = None) -> list[Path]:
    """Real clips this business has shot — lessons, tours, testimonials.

    The `ustoz` family is the only thing that puts a person on screen, and it
    cannot invent one. With this shelf empty the agent falls back to a family
    that needs no footage rather than rendering a hole.
    """
    root = get_storage().root / "brand"
    candidates: list[Path] = []
    if business_id is not None:
        candidates.append(business_dir(business_id) / "footage")
    candidates.append(root / "footage")

    found: list[Path] = []
    for folder in candidates:
        try:
            entries = sorted(p for p in folder.iterdir()
                             if p.suffix.lower() in VIDEO_SUFFIXES)
        except OSError:
            continue
        found.extend(p for p in entries if p not in found)
    return found


def footage_shelf(business_id: uuid.UUID | str) -> Path:
    """Where clips this business uploads itself are kept."""
    return business_dir(business_id) / "footage"


def own_footage(business_id: uuid.UUID | str) -> list[Path]:
    """Only this business's own clips — what an upload adds to.

    :func:`footage_library` also walks the shared shelf, which is the right
    answer for rendering and the wrong one for "how many have I sent?".
    """
    try:
        return sorted(p for p in footage_shelf(business_id).iterdir()
                      if p.suffix.lower() in VIDEO_SUFFIXES)
    except OSError:
        return []


def prop_library(business_id: uuid.UUID | str | None = None, topic: str = "") -> list[Path]:
    """3D prop renders for this business — the objects a scene is built around.

    Kept apart from :func:`photo_library` because the two are composited in
    opposite ways: a photo is framed in a circle, a prop render is screen-
    blended so its black backing disappears into the scene. Mixing the shelves
    would put a chrome object inside a photo medallion.
    """
    root = get_storage().root / "brand"
    shelf = shelf_for(topic)

    candidates: list[Path] = []
    if business_id is not None:
        own = business_dir(business_id) / "props"
        if shelf:
            candidates.append(own / shelf)
        candidates.append(own)
    if shelf:
        candidates.append(root / "props" / shelf)
    candidates.append(root / "props")

    found: list[Path] = []
    for folder in candidates:
        for path in _images(folder):
            if path not in found:
                found.append(path)
    return found


def photo_library(business_id: uuid.UUID | str | None = None, topic: str = "") -> list[Path]:
    """Backdrops for this business and topic, most specific shelf first."""
    root = get_storage().root / "brand"
    shelf = shelf_for(topic)

    candidates: list[Path] = []
    if business_id is not None:
        own = business_dir(business_id) / "photos"
        if shelf:
            candidates.append(own / shelf)
        candidates.append(own)
    if shelf:
        candidates.append(root / "photos" / shelf)
    candidates.append(root / "photos")

    for folder in candidates:
        found = _images(folder)
        if found:
            return found
    return []


def media_readiness(business_id: uuid.UUID | str) -> dict[str, object]:
    """What visual material this business actually has to build clips from.

    Every one of these degrades silently: a clip with no props still renders,
    just flatter; `ustoz` quietly falls back to another family when there is no
    footage. Silent degradation is the worst kind — the owner sees a duller
    clip and has no idea a switch is off somewhere.
    """
    from app.core.config import settings

    provider = settings.image_provider
    configured = provider != "none" and bool(
        settings.fal_api_key if provider == "fal" else settings.replicate_api_token
    )
    return {
        "props": len(prop_library(business_id)),
        "photos": len(photo_library(business_id)),
        "footage": len(footage_library(business_id)),
        "image_provider": provider,
        "image_provider_ready": configured,
    }
