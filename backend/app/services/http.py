"""Shared async HTTP plumbing: pooled clients + uniform retry policy."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import settings
from app.core.exceptions import ProviderError, RateLimitError
from app.core.logging import get_logger

log = get_logger(__name__)

_CLIENTS: dict[str, httpx.AsyncClient] = {}
_LOCK = asyncio.Lock()

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


async def get_client(name: str = "default", *, timeout: int | None = None) -> httpx.AsyncClient:
    """Return (and memoise) a pooled client per logical provider."""
    async with _LOCK:
        client = _CLIENTS.get(name)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout or settings.http_timeout, connect=15.0),
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
                follow_redirects=True,
                headers={"User-Agent": f"{settings.app_name}/1.0"},
            )
            _CLIENTS[name] = client
        return client


async def close_clients() -> None:
    async with _LOCK:
        for client in _CLIENTS.values():
            if not client.is_closed:
                await client.aclose()
        _CLIENTS.clear()


#: Longest we are willing to sit on a provider's rate-limit backoff.
MAX_RETRY_AFTER_SECONDS = 90.0

_RETRY_AFTER_RE = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)


def _retry_after_seconds(response: httpx.Response, body: Any) -> float | None:
    """Read the wait the provider asked for, from the header or the message."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(float(header), MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            pass
    text = str(body)
    match = _RETRY_AFTER_RE.search(text)
    if match:
        return min(float(match.group(1)), MAX_RETRY_AFTER_SECONDS)
    return None


def _wait_policy(state: RetryCallState) -> float:
    """Respect an explicit rate-limit delay, otherwise back off exponentially."""
    exc = state.outcome.exception() if state.outcome else None
    retry_after = getattr(exc, "retry_after", None)
    if retry_after:
        return float(retry_after)
    return wait_exponential_jitter(initial=1.5, max=20)(state)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException | httpx.NetworkError | httpx.RemoteProtocolError):
        return True
    if isinstance(exc, RateLimitError):
        # Waiting out a per-minute budget is right in a worker and wrong in a
        # chat handler, so the ceiling is configuration (LLM_MAX_RETRY_WAIT).
        return not exc.retry_after or exc.retry_after <= settings.llm_max_retry_wait
    if isinstance(exc, ProviderError):
        return exc.retryable
    return False


def raise_for_provider(provider: str, response: httpx.Response) -> None:
    """Translate a non-2xx response into a typed, retry-aware error."""
    if response.is_success:
        return
    body: Any
    try:
        body = response.json()
    except Exception:
        body = response.text[:500]

    message = f"HTTP {response.status_code}"
    if isinstance(body, dict):
        err = body.get("error") or body.get("detail") or body
        if isinstance(err, dict):
            message = str(err.get("message") or err.get("detail") or err)[:400]
        else:
            message = str(err)[:400]

    if response.status_code == 429:
        error = RateLimitError(provider, message, details=body)
        error.retry_after = _retry_after_seconds(response, body)
        raise error
    retryable = response.status_code in RETRYABLE_STATUS
    raise ProviderError(provider, message, details=body, retryable=retryable)


async def request_with_retry(
    provider: str,
    method: str,
    url: str,
    *,
    client_name: str | None = None,
    attempts: int | None = None,
    timeout: int | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP call retrying transport errors and 5xx/429 responses."""
    client = await get_client(client_name or provider, timeout=timeout)
    max_attempts = attempts or settings.ai_max_retries

    async def _once() -> httpx.Response:
        response = await client.request(method, url, **kwargs)
        raise_for_provider(provider, response)
        return response

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=_wait_policy,
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        ):
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    log.warning(
                        "http_retry",
                        provider=provider,
                        url=str(url).split("?")[0],
                        attempt=attempt.retry_state.attempt_number,
                    )
                return await _once()
    except RetryError as exc:  # pragma: no cover - tenacity reraise=True covers it
        raise ProviderError(provider, "retries exhausted", details=str(exc)) from exc
    raise ProviderError(provider, "unreachable")  # pragma: no cover
