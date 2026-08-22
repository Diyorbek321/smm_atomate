"""Instagram Content Publishing API (Meta Graph) — feed, carousel, stories.

Flow: create a media container → poll until FINISHED → publish it.
Docs: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.exceptions import ConfigurationError, PublishError
from app.core.logging import get_logger
from app.services.http import get_client
from app.utils.text import IG_CAPTION_LIMIT, truncate_caption

log = get_logger(__name__)

#: Meta error subcodes / codes that are worth retrying.
RETRYABLE_CODES = {1, 2, 4, 17, 32, 341, 368}
CAROUSEL_MIN, CAROUSEL_MAX = 2, 10
CONTAINER_POLL_ATTEMPTS = 30
CONTAINER_POLL_DELAY = 3.0


@dataclass(slots=True)
class InstagramResult:
    media_id: str
    permalink: str | None = None
    raw: dict[str, Any] | None = None


class InstagramPublisher:
    def __init__(self, access_token: str | None, ig_account_id: str | None) -> None:
        if not access_token or not ig_account_id:
            raise ConfigurationError("Instagram access token / account id is missing")
        self.token = access_token
        self.account_id = ig_account_id
        self.base = settings.graph_api_url

    # ------------------------------------------------------------------ #
    async def _request(self, method: str, path: str, **params: Any) -> dict[str, Any]:
        client = await get_client("instagram", timeout=120)
        url = f"{self.base}/{path.lstrip('/')}"
        payload = {k: v for k, v in params.items() if v is not None}
        payload["access_token"] = self.token

        try:
            if method == "GET":
                response = await client.get(url, params=payload)
            else:
                response = await client.post(url, data=payload)
        except Exception as exc:
            raise PublishError("instagram", f"network error: {exc}", retryable=True) from exc

        try:
            data = response.json()
        except Exception:
            raise PublishError(
                "instagram", f"invalid response (HTTP {response.status_code})", retryable=True
            ) from None

        if "error" in data:
            error = data["error"]
            code = int(error.get("code", 0) or 0)
            subcode = int(error.get("error_subcode", 0) or 0)
            message = error.get("message", "unknown error")
            expired = code in (190, 102) or subcode in (463, 467)
            raise PublishError(
                "instagram",
                f"{message} (code={code}, subcode={subcode})",
                retryable=(code in RETRYABLE_CODES) and not expired,
                details={"error": error, "token_expired": expired},
            )
        if not response.is_success:
            raise PublishError(
                "instagram", f"HTTP {response.status_code}", retryable=response.status_code >= 500, details=data
            )
        return data

    async def _create_container(self, **fields: Any) -> str:
        data = await self._request("POST", f"{self.account_id}/media", **fields)
        container_id = data.get("id")
        if not container_id:
            raise PublishError("instagram", "container id missing in response", details=data, retryable=False)
        return str(container_id)

    async def _await_container(self, container_id: str) -> None:
        """Block until Meta finished ingesting the asset."""
        for attempt in range(CONTAINER_POLL_ATTEMPTS):
            data = await self._request("GET", container_id, fields="status_code,status")
            status = data.get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise PublishError(
                    "instagram",
                    f"container {status}: {data.get('status', '')}",
                    retryable=False,
                    details=data,
                )
            await asyncio.sleep(CONTAINER_POLL_DELAY * (1 if attempt < 10 else 2))
        raise PublishError("instagram", "container processing timed out", retryable=True)

    async def _publish(self, container_id: str) -> InstagramResult:
        await self._await_container(container_id)
        data = await self._request("POST", f"{self.account_id}/media_publish", creation_id=container_id)
        media_id = str(data.get("id", ""))
        permalink = None
        try:
            info = await self._request("GET", media_id, fields="permalink")
            permalink = info.get("permalink")
        except PublishError:  # permalink is a nice-to-have
            pass
        log.info("instagram_published", media_id=media_id)
        return InstagramResult(media_id=media_id, permalink=permalink, raw=data)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def publish_image(self, image_url: str, caption: str = "") -> InstagramResult:
        container = await self._create_container(
            image_url=image_url, caption=truncate_caption(caption, IG_CAPTION_LIMIT)
        )
        return await self._publish(container)

    async def publish_carousel(self, image_urls: list[str], caption: str = "") -> InstagramResult:
        urls = [u for u in image_urls if u][:CAROUSEL_MAX]
        if len(urls) < CAROUSEL_MIN:
            raise PublishError(
                "instagram", f"carousel needs {CAROUSEL_MIN}-{CAROUSEL_MAX} images", retryable=False
            )
        children = [await self._create_container(image_url=url, is_carousel_item="true") for url in urls]
        for child in children:
            await self._await_container(child)
        container = await self._create_container(
            media_type="CAROUSEL",
            children=",".join(children),
            caption=truncate_caption(caption, IG_CAPTION_LIMIT),
        )
        return await self._publish(container)

    async def publish_story(self, media_url: str, *, is_video: bool = False) -> InstagramResult:
        kwargs = {"video_url": media_url} if is_video else {"image_url": media_url}
        container = await self._create_container(media_type="STORIES", **kwargs)
        return await self._publish(container)

    async def publish_reel(self, video_url: str, caption: str = "", cover_url: str | None = None) -> InstagramResult:
        container = await self._create_container(
            media_type="REELS",
            video_url=video_url,
            caption=truncate_caption(caption, IG_CAPTION_LIMIT),
            cover_url=cover_url,
            share_to_feed="true",
        )
        return await self._publish(container)

    async def publishing_limit(self) -> dict[str, Any]:
        """Remaining posts in the rolling 24h quota (25 per account)."""
        return await self._request(
            "GET", f"{self.account_id}/content_publishing_limit", fields="config,quota_usage"
        )

    async def account_info(self) -> dict[str, Any]:
        return await self._request("GET", self.account_id, fields="id,username,name,followers_count")


async def exchange_long_lived_token(short_lived_token: str) -> tuple[str, datetime | None]:
    """Swap a short-lived user token for a ~60 day token (needs app secret)."""
    if not (settings.meta_app_id and settings.meta_app_secret):
        raise ConfigurationError("META_APP_ID / META_APP_SECRET are required for token refresh")

    client = await get_client("instagram", timeout=60)
    response = await client.get(
        f"{settings.graph_api_url}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "fb_exchange_token": short_lived_token,
        },
    )
    data = response.json()
    if "error" in data or "access_token" not in data:
        raise PublishError("instagram", f"token exchange failed: {data}", retryable=False, details=data)

    expires_in = int(data.get("expires_in", 0) or 0)
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in) if expires_in else None
    return str(data["access_token"]), expires_at
