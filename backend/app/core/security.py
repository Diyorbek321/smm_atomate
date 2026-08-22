"""Secret handling: symmetric encryption for stored tokens + API-key auth."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, TypeDecorator

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_PREFIX = "enc::v1::"


@lru_cache
def _fernet() -> Fernet:
    return Fernet(settings.fernet_key)


def encrypt_secret(value: str | None) -> str | None:
    """Encrypt a plaintext secret. Already-encrypted values pass through."""
    if value is None or value == "":
        return value
    if value.startswith(_PREFIX):
        return value
    return _PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a stored secret; tolerates legacy plaintext rows."""
    if value is None or value == "":
        return value
    if not value.startswith(_PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX) :].encode()).decode()
    except InvalidToken:
        log.error("secret_decrypt_failed", hint="ENCRYPTION_KEY rotated without re-encrypting rows")
        return None


class EncryptedString(TypeDecorator):
    """SQLAlchemy column type that transparently encrypts values at rest."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        return encrypt_secret(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return decrypt_secret(value)


def mask_secret(value: str | None, keep: int = 4) -> str | None:
    """`123456789:AAH...` -> `****...cdef` for safe API/UI display."""
    if not value:
        return value
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * 8 + value[-keep:]


def verify_api_key(candidate: str | None) -> bool:
    """Constant-time-ish comparison of the dashboard API key."""
    import hmac

    if not candidate:
        return False
    return hmac.compare_digest(candidate, settings.api_key)
