"""SQLAlchemy ORM model for Audit Event."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.job import Job


class AuditEvent(Base):
    """Immutable, append-only security and operational audit event log."""

    __tablename__ = "audit_event"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique audit event record identifier",
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Associated modernization job (nullable for system/admin events)",
    )
    actor: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Identity of actor: agent name (e.g. CodeWriter) or human user",
    )
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Action performed: job_created, gate_opened, model_invoked, policy_violation...",
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Request correlation ID propagated across asynchronous workflows",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Structured, sanitized event metadata (free of passwords/secrets)",
    )
    event_time: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        comment="Timestamp when event occurred (UTC)",
    )
    event_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Audit event schema specification version",
    )

    # Relationships
    job: Mapped["Job | None"] = relationship("Job", back_populates="audit_events")

    __table_args__ = (
        Index("ix_audit_event_job_time", "job_id", "event_time"),
        Index("ix_audit_event_action_time", "action", "event_time"),
    )
