"""Domain level exceptions with HTTP-friendly metadata."""

from __future__ import annotations

from typing import Any


class AutoSMMError(Exception):
    """Base class for every error raised by this application."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"success": False, "error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFoundError(AutoSMMError):
    status_code = 404
    code = "not_found"


class ConflictError(AutoSMMError):
    status_code = 409
    code = "conflict"


class ValidationError(AutoSMMError):
    status_code = 422
    code = "validation_error"


class UnauthorizedError(AutoSMMError):
    status_code = 401
    code = "unauthorized"


class ConfigurationError(AutoSMMError):
    """A required credential / setting is missing."""

    status_code = 400
    code = "configuration_error"


class ProviderError(AutoSMMError):
    """An upstream provider (Gemini, Fal, Meta, Telegram) failed."""

    status_code = 502
    code = "provider_error"

    def __init__(self, provider: str, message: str, *, details: Any = None, retryable: bool = True) -> None:
        super().__init__(f"[{provider}] {message}", details=details)
        self.provider = provider
        self.retryable = retryable


class RateLimitError(ProviderError):
    code = "rate_limited"
    status_code = 429

    #: Seconds the provider asked us to wait, when it says so.
    retry_after: float | None = None


class TokenLimitError(ProviderError):
    """Model hit its output token ceiling — the answer is truncated."""

    code = "token_limit"
    status_code = 502


class PublishError(AutoSMMError):
    status_code = 502
    code = "publish_failed"

    def __init__(self, channel: str, message: str, *, retryable: bool = True, details: Any = None) -> None:
        super().__init__(f"[{channel}] {message}", details=details)
        self.channel = channel
        self.retryable = retryable
