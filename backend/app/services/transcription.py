"""Voice-note transcription: OpenAI Whisper with a Gemini audio fallback."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.exceptions import ConfigurationError, ProviderError
from app.core.logging import get_logger
from app.services.http import request_with_retry
from app.services.llm import get_llm

log = get_logger(__name__)


class TranscriptionService:
    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider or settings.transcription_provider

    @property
    def enabled(self) -> bool:
        if self.provider == "openai":
            return bool(settings.openai_api_key) or bool(settings.llm_key)
        if self.provider == "groq":
            return bool(settings.groq_api_key)
        return bool(settings.gemini_api_key)

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "voice.ogg",
        mime_type: str = "audio/ogg",
        language: str | None = None,
    ) -> str:
        """Return the transcript, falling back to Gemini when Whisper fails."""
        language = language or settings.default_language
        if not audio:
            raise ProviderError("transcription", "empty audio payload", retryable=False)

        if self.provider in ("openai", "groq") and self._key:
            try:
                return await self._whisper(audio, filename, language)
            except ProviderError as exc:
                log.warning("whisper_failed_fallback_llm", provider=self.provider, error=str(exc)[:200])

        # Fall back to whatever LLM is configured — Gemini and Groq both
        # understand audio, so a voice note is rarely lost.
        if not settings.llm_key:
            raise ConfigurationError(
                "no transcription provider configured (OPENAI_API_KEY / GROQ_API_KEY / GEMINI_API_KEY)"
            )
        return await get_llm().transcribe_audio(audio, mime_type=mime_type, language=language)

    async def transcribe_segments(
        self,
        audio: bytes,
        *,
        filename: str = "audio.m4a",
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Timed segments for subtitles: ``[{start, end, text}, ...]``.

        Only Whisper returns timings; without it the caller simply gets no
        subtitles rather than an error, because everything else still works.
        """
        language = language or settings.default_language
        if not audio or self.provider not in ("openai", "groq") or not self._key:
            return []

        try:
            response = await request_with_retry(
                self.provider,
                "POST",
                f"{self._base_url.rstrip('/')}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": (filename, audio, "application/octet-stream")},
                data={
                    "model": self._model,
                    "language": language if language in {"uz", "ru", "en"} else "uz",
                    "response_format": "verbose_json",
                    "temperature": "0",
                },
                timeout=300,
            )
        except ProviderError as exc:
            log.warning("whisper_segments_failed", error=str(exc)[:200])
            return []

        segments = []
        for raw in response.json().get("segments") or []:
            text = str(raw.get("text", "")).strip()
            if not text:
                continue
            segments.append(
                {"start": float(raw.get("start", 0.0)), "end": float(raw.get("end", 0.0)), "text": text}
            )
        log.info("transcript_segments", count=len(segments), provider=self.provider)
        return segments

    @property
    def _key(self) -> str:
        return settings.groq_api_key if self.provider == "groq" else settings.openai_api_key

    @property
    def _base_url(self) -> str:
        return settings.groq_base_url if self.provider == "groq" else settings.openai_base_url

    @property
    def _model(self) -> str:
        return settings.groq_whisper_model if self.provider == "groq" else settings.whisper_model

    async def _whisper(self, audio: bytes, filename: str, language: str) -> str:
        response = await request_with_retry(
            self.provider,
            "POST",
            f"{self._base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self._key}"},
            files={"file": (filename, audio, "application/octet-stream")},
            data={
                "model": self._model,
                # Whisper understands uz/ru; passing the hint improves accuracy.
                "language": language if language in {"uz", "ru", "en"} else "uz",
                "response_format": "json",
                "temperature": "0",
            },
            timeout=180,
        )
        text = str(response.json().get("text", "")).strip()
        if not text:
            raise ProviderError(self.provider, "empty transcript", retryable=False)
        log.info("voice_transcribed", chars=len(text), provider="whisper")
        return text


_service: TranscriptionService | None = None


def get_transcriber() -> TranscriptionService:
    global _service
    if _service is None:
        _service = TranscriptionService()
    return _service
