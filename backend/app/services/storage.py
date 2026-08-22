"""Media storage. Files are written to disk and served by FastAPI at /media.

Instagram fetches images by URL, so `PUBLIC_BASE_URL` must be reachable from
the internet in production (ngrok/cloudflared for local testing).
"""

from __future__ import annotations

import hashlib
import mimetypes
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.services.http import get_client

log = get_logger(__name__)

_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
}


@dataclass(slots=True)
class StoredFile:
    filename: str
    path: Path
    url: str
    size: int
    content_type: str


class MediaStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.media_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _target(self, prefix: str, ext: str) -> tuple[str, Path]:
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        folder = self.root / stamp
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{prefix}-{uuid.uuid4().hex[:12]}{ext}"
        return f"{stamp}/{name}", folder / name

    def save_bytes(self, data: bytes, *, prefix: str = "img", content_type: str = "image/png") -> StoredFile:
        ext = _EXT_BY_MIME.get(content_type) or mimetypes.guess_extension(content_type) or ".bin"
        rel_name, path = self._target(prefix, ext)
        path.write_bytes(data)
        stored = StoredFile(
            filename=rel_name,
            path=path,
            url=settings.media_url(rel_name),
            size=len(data),
            content_type=content_type,
        )
        log.info("media_saved", file=rel_name, size=stored.size)
        return stored

    async def save_from_url(self, url: str, *, prefix: str = "img") -> StoredFile:
        """Download a provider-hosted asset so we own a stable public copy."""
        client = await get_client("download", timeout=120)
        response = await client.get(url)
        if not response.is_success:
            raise ProviderError("storage", f"download failed HTTP {response.status_code}", details=url)
        content_type = (response.headers.get("content-type") or "image/png").split(";")[0].strip()
        return self.save_bytes(response.content, prefix=prefix, content_type=content_type)

    def delete(self, filename: str) -> bool:
        path = self.root / filename
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def cleanup(self, older_than_days: int | None = None) -> int:
        """Delete media past the retention window. Returns files removed.

        `brand/` and `backups/` are exempt — brand assets and database dumps
        are not generated content and must outlive the retention window.
        """
        days = older_than_days or settings.media_retention_days
        cutoff = time.time() - days * 86400
        removed = 0
        for path in self.root.rglob("*"):
            if not path.is_file() or path.name == ".gitkeep":
                continue
            if path.relative_to(self.root).parts[0] in ("brand", "backups"):
                continue
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        for folder in sorted(self.root.glob("*"), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        if removed:
            log.info("media_cleanup", removed=removed, older_than_days=days)
        return removed

    @staticmethod
    def checksum(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:16]

    @property
    def expiry_hint(self) -> datetime:
        return datetime.now(UTC) + timedelta(days=settings.media_retention_days)


_storage: MediaStorage | None = None


def get_storage() -> MediaStorage:
    global _storage
    if _storage is None:
        _storage = MediaStorage()
    return _storage


def local_media_path(url: str | None) -> Path | None:
    """Resolve a media URL we generated back to the file on disk.

    Telegram cannot fetch `http://localhost:8000/...`, so senders upload the
    bytes whenever the media is one of ours. Returns None for foreign URLs.
    """
    if not url:
        return None
    prefix = settings.media_url_prefix.rstrip("/") + "/"
    absolute = f"{settings.public_base_url.rstrip('/')}{prefix}"
    if url.startswith(absolute):
        relative = url[len(absolute) :]
    elif url.startswith(prefix):
        relative = url[len(prefix) :]
    else:
        return None

    root = Path(settings.media_root).resolve()
    candidate = (root / relative).resolve()
    if root not in candidate.parents:
        log.warning("media_path_outside_root", url=url)
        return None
    return candidate if candidate.is_file() else None
