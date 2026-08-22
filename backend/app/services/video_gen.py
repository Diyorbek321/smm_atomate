"""AI-animated clips — image-to-video via fal.ai (Seedance by default).

The montage clip in :mod:`app.services.video` is the free tier; this one sends
a brand frame to a video model so the scene itself moves (particles drift,
light breathes). Costs real money per clip, so it only runs for businesses
with ``settings["ai_video"] = true`` — the Pro tariff switch.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.exceptions import ConfigurationError, ProviderError
from app.core.logging import get_logger
from app.services.http import request_with_retry
from app.services.storage import StoredFile, get_storage

log = get_logger(__name__)

DEFAULT_MOTION_PROMPT = (
    "Slow cinematic camera push-in, golden particles drifting gently, "
    "soft light shimmer breathing across the frame, premium dark luxury "
    "brand aesthetic, smooth subtle motion, no text"
)


class VideoGenerator:
    """Image-to-video facade over fal.ai's queue-less sync endpoint."""

    @property
    def enabled(self) -> bool:
        return bool(settings.fal_api_key)

    async def animate(
        self,
        image_url: str,
        prompt: str = DEFAULT_MOTION_PROMPT,
        *,
        duration: int = 6,
        store: bool = True,
    ) -> StoredFile | str:
        """Animate a still frame. `image_url` may be an https URL or a data URI."""
        if not self.enabled:
            raise ConfigurationError("FAL_API_KEY is not configured — AI video unavailable")

        payload: dict[str, Any] = {
            "prompt": prompt,
            "image_url": image_url,
            "duration": str(duration),
            "resolution": "720p",
        }
        response = await request_with_retry(
            "fal",
            "POST",
            f"https://fal.run/{settings.fal_video_model}",
            headers={
                "Authorization": f"Key {settings.fal_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=600,                        # video models take minutes
        )
        data = response.json()
        video = (data.get("video") or {}).get("url")
        if not video:
            raise ProviderError("fal", "no video in response", details=data, retryable=False)
        if not store:
            return str(video)
        stored = await get_storage().save_from_url(str(video), prefix="aivid")
        log.info("ai_video_generated", model=settings.fal_video_model, size=stored.size)
        return stored


_generator: VideoGenerator | None = None


def get_video_generator() -> VideoGenerator:
    global _generator
    if _generator is None:
        _generator = VideoGenerator()
    return _generator
