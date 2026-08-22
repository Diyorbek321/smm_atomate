"""Client for OpenAI-compatible chat-completions endpoints (OpenAI, Groq, …).

Structured output uses the provider's strict `json_schema` mode when it is
supported and silently degrades to `json_object` plus an inline schema when it
is not, so the same agents work across providers.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.core.config import settings
from app.core.exceptions import ConfigurationError, ProviderError, RateLimitError, TokenLimitError
from app.core.logging import get_logger
from app.services.http import request_with_retry
from app.services.llm import LLMClient, LLMResult
from app.utils.json_tools import extract_json, to_openai_schema

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

#: Providers that reject `response_format.json_schema` get downgraded once and
#: remembered, so we do not pay for a failed call on every request.
_SCHEMA_MODE: dict[str, bool] = {}

def _schema_mode_rejected(exc: ProviderError) -> bool:
    """Whether the error is about structured output rather than the request.

    Providers word this several ways — "json_schema is not supported", "Failed
    to generate JSON", "does not match the expected schema" — so anything that
    mentions JSON counts. A rate limit, a truncated answer or a bad key say
    nothing about schema support and must not silently drop strict mode.
    """
    if isinstance(exc, RateLimitError | TokenLimitError):
        return False
    message = str(exc).lower()
    if any(word in message for word in ("api key", "unauthorized", "forbidden", "authentication")):
        return False
    return "json" in message or "schema" in message or "response_format" in message


class OpenAICompatibleClient(LLMClient):
    def __init__(
        self,
        provider: str = "openai",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.provider = provider
        self._api_key = api_key
        self._base_url = base_url

    # ------------------------------------------------------------------ #
    @property
    def api_key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        return settings.groq_api_key if self.provider == "groq" else settings.openai_api_key

    @property
    def base_url(self) -> str:
        if self._base_url is not None:
            return self._base_url.rstrip("/")
        url = settings.groq_base_url if self.provider == "groq" else settings.openai_base_url
        return url.rstrip("/")

    @property
    def model_fast(self) -> str:
        return settings.groq_model_fast if self.provider == "groq" else settings.openai_model_fast

    @property
    def model_pro(self) -> str:
        return settings.groq_model_pro if self.provider == "groq" else settings.openai_model_pro

    def _require_key(self) -> str:
        key = self.api_key
        if not key:
            raise ConfigurationError(
                f"{self.provider.upper()}_API_KEY is not configured (LLM_PROVIDER={self.provider})"
            )
        return key

    # ------------------------------------------------------------------ #
    async def _chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResult:
        key = self._require_key()
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        try:
            response = await request_with_retry(
                self.provider,
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=max(settings.http_timeout, 180),
            )
        except ProviderError as exc:
            # Some models reject `temperature`; retry once at the default.
            if "temperature" in str(exc).lower() and temperature != 1.0:
                log.warning("llm_temperature_unsupported", provider=self.provider, model=model)
                payload["temperature"] = 1.0
                response = await request_with_retry(
                    self.provider,
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=max(settings.http_timeout, 180),
                )
            else:
                raise

        return self._parse(response.json(), model)

    def _parse(self, data: dict[str, Any], model: str) -> LLMResult:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(self.provider, "no choices returned", details=data, retryable=True)

        choice = choices[0]
        message = choice.get("message") or {}
        text = (message.get("content") or "").strip()
        finish = choice.get("finish_reason", "stop")
        usage = data.get("usage") or {}

        result = LLMResult(
            text=text,
            model=model,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            finish_reason=finish,
            provider=self.provider,
            raw=data,
        )

        if finish == "length":
            raise TokenLimitError(
                self.provider,
                "output truncated at max_completion_tokens",
                details=result.meta(),
                retryable=False,
            )
        if finish == "content_filter":
            raise ProviderError(self.provider, "blocked by the content filter", details=choice, retryable=False)
        if not text:
            raise ProviderError(self.provider, "empty completion", details=choice, retryable=True)
        return result

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
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        return await self._chat(
            messages,
            model=model or self.model_fast,
            temperature=settings.llm_temperature if temperature is None else temperature,
            max_tokens=max_tokens or settings.llm_max_output_tokens,
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
        model_name = model or self.model_fast
        temp = settings.llm_temperature if temperature is None else temperature
        budget = max_tokens or settings.llm_max_output_tokens
        json_schema = to_openai_schema(schema)

        base_messages: list[dict[str, Any]] = []
        if system:
            base_messages.append({"role": "system", "content": system})

        use_strict = _SCHEMA_MODE.get(f"{self.provider}:{model_name}", True)

        async def _call(user_prompt: str, strict: bool) -> LLMResult:
            messages = [*base_messages]
            if strict:
                messages.append({"role": "user", "content": user_prompt})
                fmt = {
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "strict": True, "schema": json_schema},
                }
            else:
                # Without schema enforcement the model needs to see the shape.
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"{user_prompt}\n\nFAQAT shu JSON sxemasiga mos JSON qaytar "
                            f"(izohsiz, markdown'siz):\n{json.dumps(json_schema, ensure_ascii=False)}"
                        ),
                    }
                )
                fmt = {"type": "json_object"}
            return await self._chat(
                messages, model=model_name, temperature=temp, max_tokens=budget, response_format=fmt
            )

        try:
            result = await _call(prompt, use_strict)
        except ProviderError as exc:
            if use_strict and _schema_mode_rejected(exc):
                log.warning(
                    "llm_json_schema_unsupported_fallback",
                    provider=self.provider,
                    model=model_name,
                    error=str(exc)[:200],
                )
                _SCHEMA_MODE[f"{self.provider}:{model_name}"] = False
                use_strict = False
                result = await _call(prompt, False)
            elif isinstance(exc, TokenLimitError):
                log.warning("llm_token_limit_retry", provider=self.provider, model=model_name)
                result = await _call(
                    prompt + "\n\nMUHIM: javobni imkon qadar QISQA qil, faqat majburiy maydonlar.",
                    use_strict,
                )
            else:
                raise

        last_error: Exception | None = None
        for attempt in range(repair_attempts + 1):
            try:
                return schema.model_validate(extract_json(result.text)), result
            except (ValueError, PydanticValidationError) as exc:
                last_error = exc
                if attempt >= repair_attempts:
                    break
                log.warning("llm_json_repair", provider=self.provider, error=str(exc)[:200])
                result = await _call(
                    "Quyidagi JSON noto'g'ri. Xatoni tuzatib, FAQAT to'g'ri JSON qaytar.\n\n"
                    f"XATO: {str(exc)[:500]}\n\nJSON:\n{result.text[:6000]}",
                    use_strict,
                )

        raise ProviderError(
            self.provider,
            f"structured output validation failed: {last_error}",
            details=result.text[:1000],
            retryable=False,
        )

    async def transcribe_audio(
        self, audio: bytes, mime_type: str = "audio/ogg", language: str = "uz"
    ) -> str:
        """Whisper through the same OpenAI-compatible surface."""
        key = self._require_key()
        model = settings.groq_whisper_model if self.provider == "groq" else settings.whisper_model
        extension = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a"}.get(mime_type, "ogg")

        response = await request_with_retry(
            self.provider,
            "POST",
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (f"voice.{extension}", audio, "application/octet-stream")},
            data={
                "model": model,
                "language": language if language in {"uz", "ru", "en"} else "uz",
                "response_format": "json",
                "temperature": "0",
            },
            timeout=180,
        )
        text = str(response.json().get("text", "")).strip()
        if not text:
            raise ProviderError(self.provider, "empty transcript", retryable=False)
        return text
