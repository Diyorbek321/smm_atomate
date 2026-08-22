"""Google Gemini client (REST) — text, structured JSON and audio understanding.

Talking to the REST endpoint directly (instead of a vendor SDK) keeps the
dependency surface small and lets us control retries, token budgets and the
`responseSchema` conversion ourselves.
"""

from __future__ import annotations

import base64
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.core.config import settings
from app.core.exceptions import ConfigurationError, ProviderError, TokenLimitError
from app.core.logging import get_logger
from app.services.http import request_with_retry
from app.services.llm import LLMClient, LLMResult
from app.utils.json_tools import extract_json, to_gemini_schema

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

PROVIDER = "gemini"

#: Kept as an alias so existing imports (and tests) keep working.
GeminiResult = LLMResult

#: Models that rejected `thinkingConfig` — asked for once, then remembered.
_THINKING_SUPPORTED: dict[str, bool] = {}

_SAFETY_SETTINGS = [
    {"category": c, "threshold": "BLOCK_ONLY_HIGH"}
    for c in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
]


class GeminiClient(LLMClient):
    """Thin, retry-aware wrapper around `models/{model}:generateContent`."""

    provider = PROVIDER
    supports_documents = True

    @property
    def model_fast(self) -> str:
        return settings.gemini_model_fast

    @property
    def model_pro(self) -> str:
        return settings.gemini_model_pro

    def __init__(self, api_key: str | None = None) -> None:
        #: `None` means "resolve from settings at call time" — the client is a
        #: process-wide singleton, so it must not freeze configuration.
        self._api_key = api_key

    @property
    def api_key(self) -> str:
        return self._api_key if self._api_key is not None else settings.gemini_api_key

    @property
    def base_url(self) -> str:
        return settings.gemini_base_url.rstrip("/")

    # ------------------------------------------------------------------ #
    # Low level
    # ------------------------------------------------------------------ #
    def _require_key(self) -> str:
        key = self.api_key
        if not key:
            raise ConfigurationError("GEMINI_API_KEY is not configured")
        return key

    async def _generate(
        self,
        parts: list[dict[str, Any]],
        *,
        model: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        key = self._require_key()
        url = f"{self.base_url}/models/{model}:generateContent"

        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "topP": 0.95,
        }
        if response_schema is not None:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = response_schema

        thinking = settings.gemini_thinking_budget
        use_thinking = thinking is not None and _THINKING_SUPPORTED.get(model, True)
        if use_thinking:
            generation_config["thinkingConfig"] = {"thinkingBudget": thinking}

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
            "safetySettings": _SAFETY_SETTINGS,
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        try:
            response = await request_with_retry(
                PROVIDER,
                "POST",
                url,
                params={"key": key},
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=max(settings.http_timeout, 120),
            )
        except ProviderError as exc:
            # Older models do not know `thinkingConfig`; drop it and remember.
            if use_thinking and "thinking" in str(exc).lower():
                log.info("gemini_thinking_unsupported", model=model)
                _THINKING_SUPPORTED[model] = False
                generation_config.pop("thinkingConfig", None)
                response = await request_with_retry(
                    PROVIDER,
                    "POST",
                    url,
                    params={"key": key},
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=max(settings.http_timeout, 120),
                )
            else:
                raise

        return self._parse(response.json(), model)

    @staticmethod
    def _parse(data: dict[str, Any], model: str) -> LLMResult:
        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback", {})
            reason = feedback.get("blockReason", "no candidates returned")
            raise ProviderError(PROVIDER, f"generation blocked: {reason}", details=feedback, retryable=False)

        candidate = candidates[0]
        finish = candidate.get("finishReason", "STOP")
        chunks = [p.get("text", "") for p in candidate.get("content", {}).get("parts", [])]
        text = "".join(chunks).strip()

        usage = data.get("usageMetadata", {})
        result = LLMResult(
            text=text,
            model=model,
            prompt_tokens=int(usage.get("promptTokenCount", 0) or 0),
            output_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
            finish_reason=finish,
            provider=PROVIDER,
            raw=data,
        )

        if finish == "MAX_TOKENS":
            raise TokenLimitError(
                PROVIDER,
                "output truncated at maxOutputTokens — retry with a smaller request",
                details=result.meta(),
                retryable=False,
            )
        if finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise ProviderError(PROVIDER, f"generation stopped: {finish}", details=candidate, retryable=False)
        if not text:
            raise ProviderError(PROVIDER, "empty completion", details=candidate, retryable=True)
        return result

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        return await self._generate(
            [{"text": prompt}],
            model=model or settings.gemini_model_fast,
            system=system,
            temperature=settings.gemini_temperature if temperature is None else temperature,
            max_tokens=max_tokens or settings.gemini_max_output_tokens,
        )

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        repair_attempts: int = 1,
    ) -> tuple[T, LLMResult]:
        """Return a validated Pydantic object plus usage metadata.

        Uses Gemini's native JSON mode; if the payload still fails validation
        we ask the model once more to repair it against the error message.
        """
        return await self._structured(
            prompt,
            schema,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            repair_attempts=repair_attempts,
        )

    async def generate_structured_document(
        self,
        prompt: str,
        schema: type[T],
        *,
        data: bytes,
        mime_type: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[T, LLMResult]:
        """Structured extraction with a document (e.g. PDF) attached inline."""
        attachment = {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(data).decode()}}
        return await self._structured(
            prompt,
            schema,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            repair_attempts=1,
            attachments=[attachment],
        )

    async def _structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        repair_attempts: int,
        attachments: list[dict[str, Any]] | None = None,
    ) -> tuple[T, LLMResult]:
        response_schema = to_gemini_schema(schema)
        model_name = model or settings.gemini_model_fast
        temp = settings.gemini_temperature if temperature is None else temperature
        budget = max_tokens or settings.gemini_max_output_tokens
        extra = attachments or []

        try:
            result = await self._generate(
                [{"text": prompt}, *extra],
                model=model_name,
                system=system,
                temperature=temp,
                max_tokens=budget,
                response_schema=response_schema,
            )
        except TokenLimitError:
            # Truncated JSON is unusable — retry once with a tighter budget and
            # an explicit brevity instruction.
            log.warning("gemini_token_limit_retry", model=model_name)
            result = await self._generate(
                [
                    {"text": prompt + "\n\nMUHIM: javobni imkon qadar QISQA qil, faqat majburiy maydonlar."},
                    *extra,
                ],
                model=model_name,
                system=system,
                temperature=min(temp, 0.6),
                max_tokens=budget,
                response_schema=response_schema,
            )

        last_error: Exception | None = None
        for attempt in range(repair_attempts + 1):
            try:
                payload = extract_json(result.text)
                return schema.model_validate(payload), result
            except (ValueError, PydanticValidationError) as exc:
                last_error = exc
                if attempt >= repair_attempts:
                    break
                log.warning("gemini_json_repair", model=model_name, error=str(exc)[:200])
                result = await self._generate(
                    [
                        {
                            "text": (
                                "Quyidagi JSON noto'g'ri formatda. Xatoni tuzatib, FAQAT to'g'ri JSON qaytar.\n\n"
                                f"XATO: {str(exc)[:500]}\n\nJSON:\n{result.text[:6000]}"
                            )
                        }
                    ],
                    model=model_name,
                    system="You are a JSON repair tool. Output only valid JSON matching the requested schema.",
                    temperature=0.1,
                    max_tokens=budget,
                    response_schema=response_schema,
                )

        raise ProviderError(
            PROVIDER,
            f"structured output validation failed: {last_error}",
            details=result.text[:1000],
            retryable=False,
        )

    async def transcribe_audio(self, audio: bytes, mime_type: str = "audio/ogg", language: str = "uz") -> str:
        """Fallback transcription path when Whisper is not configured."""
        prompt = (
            f"Transcribe this voice message verbatim. The speaker talks in {language} "
            "(Uzbek, possibly mixed with Russian). Return ONLY the transcript text."
        )
        result = await self._generate(
            [
                {"text": prompt},
                {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(audio).decode()}},
            ],
            model=settings.gemini_model_fast,
            system=None,
            temperature=0.0,
            max_tokens=2048,
        )
        return result.text.strip()


_client: GeminiClient | None = None


def get_gemini() -> GeminiClient:
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
