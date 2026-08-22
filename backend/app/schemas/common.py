"""Shared response envelope and pagination helpers."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: Any | None = None


class PageMeta(BaseModel):
    total: int = 0
    page: int = 1
    limit: int = 20

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.limit))


class APIResponse(BaseModel, Generic[T]):
    """Uniform envelope used by every endpoint."""

    success: bool = True
    data: T | None = None
    error: ErrorInfo | None = None
    meta: PageMeta | None = None

    @classmethod
    def ok(cls, data: T, meta: PageMeta | None = None) -> APIResponse[T]:
        return cls(success=True, data=data, meta=meta)

    @classmethod
    def fail(cls, code: str, message: str, details: Any = None) -> APIResponse[T]:
        return cls(success=False, data=None, error=ErrorInfo(code=code, message=message, details=details))


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


class MessageResponse(BaseModel):
    message: str
    detail: Any | None = None
