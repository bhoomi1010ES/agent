"""SQLAlchemy ORM model for background task persistence and worker lease tracking."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base, TimestampMixin
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.job import Job


class Task(Base, TimestampMixin):
    """Background task persistence record with atomic worker lease coordination."""

    __tablename__ = "task"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique task identifier",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Job to which this task belongs",
    )
    task_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Durable task type or handler identifier",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="Task status: pending, running, retry_wait, completed, failed, cancelled",
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Identifier of the worker currently holding the lease",
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        index=True,
        comment="UTC timestamp when the current lease expires",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of times execution has been attempted",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        comment="Maximum allowed execution attempts",
    )
    retry_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        index=True,
        comment="Earliest UTC timestamp when task can be claimed after retry_wait",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Task input payload or durable references",
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Task execution result payload or summary",
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error description from the most recent failed attempt",
    )
    failure_classification: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Classification of last failure determining retryability",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        comment="UTC timestamp when task was first leased",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        comment="UTC timestamp when task reached terminal status",
    )
    workflow_thread_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="LangGraph workflow thread identifier if linked",
    )
    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Reason provided when task was cancelled",
    )

    job: Mapped["Job"] = relationship("Job", back_populates="tasks", lazy="selectin")

    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_task_attempt_count_non_negative"),
        CheckConstraint("max_attempts >= 1", name="ck_task_max_attempts_positive"),
        CheckConstraint(
            "status IN ('pending', 'running', 'retry_wait', 'completed', 'failed', 'cancelled')",
            name="ck_task_status_allowed",
        ),
        Index("ix_task_claim_lookup", "status", "retry_at", "lease_expires_at", "created_at"),
        Index("ix_task_recovery_lookup", "status", "lease_expires_at"),
        Index("ix_task_job_status", "job_id", "status"),
    )


__all__ = ["Task"]
