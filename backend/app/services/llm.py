"""Provider-agnostic LLM layer.

The agents never talk to a vendor directly — they go through `get_llm()`, so
switching between Gemini and any OpenAI-compatible endpoint (OpenAI, Groq,
a local gateway) is a configuration change, not a code change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import ConfigurationError, ProviderError
from app.core.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

#: USD per 1M tokens (input, output) — public list prices, for cost estimates.
PRICING: dict[str, tuple[float, float]] = {
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "openai/gpt-oss-20b": (0.10, 0.50),
    "openai/gpt-oss-120b": (0.15, 0.75),
    "qwen/qwen3.6-27b": (0.20, 0.60),
}
DEFAULT_PRICE = (0.15, 0.60)


@dataclass(slots=True)
class LLMResult:
    """One completion plus the accounting that goes with it."""

    text: str
    model: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    provider: str = "llm"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        rate_in, rate_out = PRICING.get(
            self.model, PRICING.get(self.model.split("/")[-1], DEFAULT_PRICE)
        )
        return round(self.prompt_tokens / 1e6 * rate_in + self.output_tokens / 1e6 * rate_out, 6)

    def meta(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "finish_reason": self.finish_reason,
        }


class LLMClient(ABC):
    """Everything the agents need from a language model."""

    provider: str = "llm"
    #: Whether the provider accepts inline documents (PDF) in a prompt.
    supports_documents: bool = False

    @property
    @abstractmethod
    def model_fast(self) -> str: ...

    @property
    @abstractmethod
    def model_pro(self) -> str: ...

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult: ...

    @abstractmethod
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
    ) -> tuple[T, LLMResult]: ...

    @abstractmethod
    async def transcribe_audio(
        self, audio: bytes, mime_type: str = "audio/ogg", language: str = "uz"
    ) -> str: ...

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
        """Structured extraction from an attached document (PDF and the like).

        Not abstract on purpose: only multimodal providers can do this, the
        rest keep the default and refuse with a configuration error.
        """
        raise ConfigurationError(
            f"LLM provider '{self.provider}' cannot read documents — use LLM_PROVIDER=gemini"
        )


_client: LLMClient | None = None
_client_provider: str | None = None


class FallbackLLM(LLMClient):
    """Tries each provider in turn — a daily quota must not stop the service.

    Only the primary receives an explicit `model` argument: model names are
    provider-specific, so a fallback is asked for its own default instead.
    """

    provider = "fallback"

    def __init__(self, clients: list[LLMClient]) -> None:
        if not clients:
            raise ConfigurationError("no LLM provider configured")
        self.clients = clients

    @property
    def supports_documents(self) -> bool:                      # type: ignore[override]
        return any(client.supports_documents for client in self.clients)

    @property
    def model_fast(self) -> str:
        return self.clients[0].model_fast

    @property
    def model_pro(self) -> str:
        return self.clients[0].model_pro

    async def _attempt(self, method: str, *args: Any, model: str | None = None, **kwargs: Any):
        last: Exception | None = None
        for index, client in enumerate(self.clients):
            try:
                chosen = model if index == 0 else None
                return await getattr(client, method)(*args, model=chosen, **kwargs)
            except (ProviderError, ConfigurationError) as exc:
                last = exc
                if index + 1 < len(self.clients):
                    log.warning(
                        "llm_provider_switched",
                        frm=client.provider,
                        to=self.clients[index + 1].provider,
                        error=str(exc)[:200],
                    )
        raise last if last else ConfigurationError("no LLM provider answered")

    async def generate_text(self, prompt: str, **kwargs: Any) -> LLMResult:
        return await self._attempt("generate_text", prompt, **kwargs)

    async def generate_structured(self, prompt: str, schema: type[T], **kwargs: Any):
        return await self._attempt("generate_structured", prompt, schema, **kwargs)

    async def generate_structured_document(self, prompt: str, schema: type[T], **kwargs: Any):
        for client in self.clients:
            if client.supports_documents:
                return await client.generate_structured_document(prompt, schema, **kwargs)
        raise ConfigurationError("no configured provider can read documents")

    async def transcribe_audio(
        self, audio: bytes, mime_type: str = "audio/ogg", language: str = "uz"
    ) -> str:
        last: Exception | None = None
        for client in self.clients:
            try:
                return await client.transcribe_audio(audio, mime_type, language)
            except (ProviderError, ConfigurationError) as exc:
                last = exc
        raise last if last else ConfigurationError("no transcription provider answered")


def _build_client(provider: str) -> LLMClient:
    if provider == "gemini":
        from app.services.gemini import GeminiClient

        return GeminiClient()
    from app.services.openai_compat import OpenAICompatibleClient

    return OpenAICompatibleClient(provider=provider)


def _configured(provider: str) -> bool:
    """A provider without a key is not a fallback, it is a dead end."""
    if provider == "gemini":
        return bool(settings.gemini_api_key)
    if provider == "groq":
        return bool(settings.groq_api_key)
    if provider == "openai":
        return bool(settings.openai_api_key)
    return False


def provider_chain() -> list[str]:
    """Primary first, then every configured fallback, without repeats."""
    chain = [settings.llm_provider]
    for name in settings.llm_fallbacks.split(","):
        name = name.strip().lower()
        if name and name not in chain and _configured(name):
            chain.append(name)
    return chain


def get_llm() -> LLMClient:
    """Return the configured client, rebuilding it when the chain changes."""
    global _client, _client_provider

    chain = provider_chain()
    signature = ",".join(chain)
    if _client is not None and _client_provider == signature:
        return _client

    clients = [_build_client(name) for name in chain]
    _client = clients[0] if len(clients) == 1 else FallbackLLM(clients)
    _client_provider = signature
    log.info("llm_client_ready", chain=signature, model=_client.model_fast)
    return _client


def get_document_llm() -> LLMClient:
    """Client used for document understanding (PDF ingest).

    The active provider when it can read documents; otherwise Gemini when a
    key is configured — the same spirit as the Whisper → Gemini transcription
    fallback, so a Groq-first deployment still gets PDF ingest.
    """
    client = get_llm()
    if client.supports_documents:
        return client
    if settings.gemini_api_key:
        from app.services.gemini import get_gemini

        return get_gemini()
    raise ConfigurationError(
        f"LLM provider '{client.provider}' cannot read documents and GEMINI_API_KEY is not set"
    )


def reset_llm() -> None:
    """Drop the cached client — used by tests and after a settings change."""
    global _client, _client_provider
    _client = None
    _client_provider = None
