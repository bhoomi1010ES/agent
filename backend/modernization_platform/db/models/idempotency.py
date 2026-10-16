"""SQLAlchemy ORM model for Idempotency Records."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from modernization_platform.db.base import Base, ImmutableTimestampMixin
from modernization_platform.db.types import GUID, UTCDateTime


class IdempotencyRecord(Base, ImmutableTimestampMixin):
    """Persisted idempotency execution record preventing duplicate side-effects."""

    __tablename__ = "idempotency_record"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "action",
            "key",
            name="uq_idempotency_tenant_user_action_key",
        ),
        Index("ix_idempotency_lookup", "tenant_id", "user_id", "action", "key"),
    )


__all__ = ["IdempotencyRecord"]
