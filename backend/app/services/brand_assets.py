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
