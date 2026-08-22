"""Declarative base and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def as_dict(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        pk = getattr(self, "id", None)
        return f"<{self.__class__.__name__} id={pk}>"


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    """Created/updated stamps.

    ``onupdate`` is a *Python* callable on purpose: a SQL-side ``now()`` would
    expire the attribute after every flush, and serialising an expired column
    outside the async greenlet raises ``MissingGreenlet``.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow, nullable=False
    )
