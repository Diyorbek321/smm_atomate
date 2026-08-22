"""Publishing service — dispatches an approved ContentItem to every channel."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConfigurationError, PublishError
from app.core.logging import get_logger
from app.models.business import Business, BusinessCredentials
from app.models.content_item import ContentItem
from app.models.enums import ContentItemStatus, ContentType, Platform, PublishState
from app.models.publish_log import PublishLog
from app.utils.dates import utcnow
from app.utils.text import TG_MESSAGE_LIMIT, truncate_caption

log = get_logger(__name__)


@dataclass(slots=True)
class ChannelOutcome:
    platform: Platform
    state: PublishState
    external_id: str | None = None
    message: str = ""
    retryable: bool = True
    duration_ms: int = 0


@dataclass(slots=True)
class PublishResult:
    item_id: str
    outcomes: list[ChannelOutcome] = field(default_factory=list)

    @property
    def any_success(self) -> bool:
        return any(o.state == PublishState.SUCCESS for o in self.outcomes)

    @property
    def all_done(self) -> bool:
        return all(o.state in (PublishState.SUCCESS, PublishState.SKIPPED) for o in self.outcomes)

    @property
    def retryable(self) -> bool:
        return any(o.state == PublishState.FAILED and o.retryable for o in self.outcomes)

    @property
    def all_skipped(self) -> bool:
        """Nothing was even attempted — the business has no channel configured."""
        return bool(self.outcomes) and all(o.state == PublishState.SKIPPED for o in self.outcomes)

    @property
    def skip_reasons(self) -> str:
        return "; ".join(
            f"{o.platform.value}: {o.message}" for o in self.outcomes if o.state == PublishState.SKIPPED
        )

    @property
    def errors(self) -> str:
        return "; ".join(f"{o.platform.value}: {o.message}" for o in self.outcomes if o.state == PublishState.FAILED)


class PublishingService:
    """Knows how each content type maps onto Telegram and Instagram."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def publish(self, item: ContentItem, business: Business, *, force: bool = False) -> PublishResult:
        credentials = business.credentials
        result = PublishResult(item_id=str(item.id))

        if item.status == ContentItemStatus.PUBLISHED and not force:
            log.info("publish_skipped_already_published", item=str(item.id))
            return result

        item.status = ContentItemStatus.PUBLISHING
        await self.session.flush()

        if item.needs_telegram:
            result.outcomes.append(await self._telegram(item, business, credentials))
        if item.needs_instagram:
            result.outcomes.append(await self._instagram(item, business, credentials))

        if not result.outcomes:
            result.outcomes.append(
                ChannelOutcome(Platform.TELEGRAM, PublishState.SKIPPED, message="no channel enabled", retryable=False)
            )

        self._finalize(item, result)
        await self.session.flush()
        return result

    # ------------------------------------------------------------------ #
    def _finalize(self, item: ContentItem, result: PublishResult) -> None:
        for outcome in result.outcomes:
            if outcome.platform == Platform.TELEGRAM:
                item.tg_state = outcome.state
                item.tg_message_id = outcome.external_id or item.tg_message_id
            elif outcome.platform == Platform.INSTAGRAM:
                item.ig_state = outcome.state
                item.ig_media_id = outcome.external_id or item.ig_media_id

            self.session.add(
                PublishLog(
                    content_item_id=item.id,
                    business_id=item.business_id,
                    platform=outcome.platform,
                    state=outcome.state,
                    attempt=item.retry_count + 1,
                    external_id=outcome.external_id,
                    message=outcome.message[:2000] if outcome.message else None,
                    duration_ms=outcome.duration_ms,
                )
            )

        if result.all_skipped:
            # A configuration gap, not a transient error: retrying every 15
            # minutes forever would just spam the logs. Fail it once, loudly.
            item.status = ContentItemStatus.FAILED
            item.retry_count = settings.max_publish_retries
            item.last_error = f"no channel configured — {result.skip_reasons}"[:2000]
        elif result.any_success and result.all_done:
            item.status = ContentItemStatus.PUBLISHED
            item.published_at = utcnow()
            item.last_error = None
        elif result.any_success:
            # Partially delivered: keep it published but record what failed.
            item.status = ContentItemStatus.PUBLISHED
            item.published_at = utcnow()
            item.last_error = result.errors[:2000]
        else:
            item.status = ContentItemStatus.FAILED
            item.retry_count += 1
            item.last_error = result.errors[:2000] or "publish failed"

        log.info(
            "publish_finished",
            item=str(item.id),
            status=str(item.status),
            outcomes=[(o.platform.value, o.state.value) for o in result.outcomes],
        )

    # ------------------------------------------------------------------ #
    # Telegram
    # ------------------------------------------------------------------ #
    async def _telegram(
        self, item: ContentItem, business: Business, credentials: BusinessCredentials | None
    ) -> ChannelOutcome:
        from app.services.telegram_publisher import TelegramPublisher

        started = time.perf_counter()
        token = (credentials.tg_bot_token if credentials else None) or settings.telegram_bot_token
        channel = credentials.tg_channel_id if credentials else None

        if not (credentials and credentials.telegram_enabled) or not channel or not token:
            return ChannelOutcome(
                Platform.TELEGRAM,
                PublishState.SKIPPED,
                message="telegram not configured",
                retryable=False,
            )

        try:
            publisher = TelegramPublisher(token)
            caption = item.caption_tg or item.headline

            if item.content_type == ContentType.TELEGRAM_QUIZ:
                quiz = item.options or {}
                if caption.strip():
                    await publisher.send_message(channel, truncate_caption(caption, TG_MESSAGE_LIMIT))
                sent = await publisher.send_quiz(
                    channel,
                    str(quiz.get("question", item.headline or item.topic)),
                    list(quiz.get("answers", [])),
                    correct_option_id=int(quiz.get("correct_option_id", 0) or 0),
                    explanation=str(quiz.get("explanation", "")),
                )
            elif item.content_type == ContentType.CAROUSEL and item.slide_image_urls:
                sent = await publisher.send_album(channel, item.slide_image_urls, caption)
            elif item.content_type == ContentType.REELS_SCRIPT:
                sent = await publisher.send_message(channel, self._reels_message(item))
            elif item.video_url:
                sent = await publisher.send_video(channel, item.video_url, caption)
            elif item.image_url:
                sent = await publisher.send_photo(channel, item.image_url, caption)
            else:
                sent = await publisher.send_message(channel, caption)

            return ChannelOutcome(
                Platform.TELEGRAM,
                PublishState.SUCCESS,
                external_id=sent.message_id,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except (PublishError, ConfigurationError) as exc:
            retryable = getattr(exc, "retryable", False)
            log.error("telegram_publish_failed", item=str(item.id), error=str(exc)[:300])
            return ChannelOutcome(
                Platform.TELEGRAM,
                PublishState.FAILED,
                message=str(exc),
                retryable=bool(retryable),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            log.exception("telegram_publish_crashed", item=str(item.id))
            return ChannelOutcome(Platform.TELEGRAM, PublishState.FAILED, message=str(exc)[:400])

    @staticmethod
    def _reels_message(item: ContentItem) -> str:
        """Reels scripts are delivered to the team as a formatted checklist."""
        script: dict[str, Any] = item.script or {}
        lines = [f"<b>🎬 REELS SSENARIY — {item.headline or item.topic}</b>"]
        if script.get("duration_sec"):
            lines.append(f"⏱ {script['duration_sec']} soniya")
        for scene in script.get("scenes", [])[:12]:
            lines.append(
                f"\n<b>{scene.get('t', '')}</b>\n📹 {scene.get('shot', '')}\n"
                f"💬 {scene.get('on_screen', '')}\n🎙 {scene.get('voice', '')}"
            )
        if script.get("voiceover"):
            lines.append(f"\n<b>Voiceover:</b>\n{script['voiceover']}")
        if item.caption_tg:
            lines.append(f"\n<b>Post matni:</b>\n{item.caption_tg}")
        return truncate_caption("\n".join(lines), TG_MESSAGE_LIMIT)

    # ------------------------------------------------------------------ #
    # Instagram
    # ------------------------------------------------------------------ #
    async def _instagram(
        self, item: ContentItem, business: Business, credentials: BusinessCredentials | None
    ) -> ChannelOutcome:
        from app.services.instagram_publisher import InstagramPublisher

        started = time.perf_counter()
        if not business.capabilities.instagram:
            return ChannelOutcome(
                Platform.INSTAGRAM,
                PublishState.SKIPPED,
                message=f"instagram not included in the {business.plan} plan",
                retryable=False,
            )
        if not credentials or not credentials.instagram_ready:
            return ChannelOutcome(
                Platform.INSTAGRAM,
                PublishState.SKIPPED,
                message="instagram not configured",
                retryable=False,
            )

        try:
            publisher = InstagramPublisher(credentials.ig_access_token, credentials.ig_account_id)
            caption = item.caption_ig or item.caption_tg

            if item.content_type == ContentType.CAROUSEL and len(item.slide_image_urls) >= 2:
                published = await publisher.publish_carousel(item.slide_image_urls, caption)
            elif item.content_type == ContentType.STORY and (item.video_url or item.image_url):
                published = await publisher.publish_story(
                    item.video_url or item.image_url, is_video=bool(item.video_url)
                )
            elif item.image_url:
                published = await publisher.publish_image(item.image_url, caption)
            else:
                return ChannelOutcome(
                    Platform.INSTAGRAM,
                    PublishState.SKIPPED,
                    message="no image available for instagram",
                    retryable=False,
                )

            return ChannelOutcome(
                Platform.INSTAGRAM,
                PublishState.SUCCESS,
                external_id=published.media_id,
                message=published.permalink or "",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except (PublishError, ConfigurationError) as exc:
            retryable = getattr(exc, "retryable", False)
            details = getattr(exc, "details", None) or {}
            if isinstance(details, dict) and details.get("token_expired"):
                log.error("instagram_token_expired", business=str(business.id))
            log.error("instagram_publish_failed", item=str(item.id), error=str(exc)[:300])
            return ChannelOutcome(
                Platform.INSTAGRAM,
                PublishState.FAILED,
                message=str(exc),
                retryable=bool(retryable),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            log.exception("instagram_publish_crashed", item=str(item.id))
            return ChannelOutcome(Platform.INSTAGRAM, PublishState.FAILED, message=str(exc)[:400])
