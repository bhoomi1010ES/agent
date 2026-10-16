"""SQLAlchemy ORM model for modernization Job."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base, TimestampMixin
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.agent_run import AgentRun
    from modernization_platform.db.models.artifact import Artifact
    from modernization_platform.db.models.audit_event import AuditEvent
    from modernization_platform.db.models.budget import BudgetAccount
    from modernization_platform.db.models.gate import Gate
    from modernization_platform.db.models.model_execution import ModelExecution
    from modernization_platform.db.models.module import Module
    from modernization_platform.db.models.source_provenance import SourceProvenanceRecord
    from modernization_platform.db.models.task import Task
    from modernization_platform.db.models.test_case import TestCase


class Job(Base, TimestampMixin):
    """Modernization execution job tracking lifecycle, budget, version, and artifacts."""

    __tablename__ = "job"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique job identifier",
    )
    owner: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Owner user or organization identity",
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Tenant authorization boundary; null only for pre-01.4 legacy rows",
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("user_account.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Stable owner identity; null only for pre-01.4 legacy rows",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="queued",
        index=True,
        comment="Lifecycle status: queued, running, awaiting_approval, paused, failed, cancelled, completed",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Monotonically increasing version for optimistic concurrency control",
    )
    source_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Source repository URL, Git commit hash, or path",
    )
    source_revision: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Explicit source revision or commit identifier",
    )
    target_stack_spec: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Target architecture and stack specification",
    )
    budget: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Budget thresholds and execution limits",
    )
    current_stage: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Current workflow execution stage",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        comment="Timestamp when job execution transitioned to running",
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        comment="Timestamp when job was paused",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        comment="Timestamp when job reached successful completion",
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        comment="Timestamp when job was cancelled",
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        comment="Timestamp when job encountered a failure",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        comment="Timestamp when job reached any terminal state",
    )
    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="Reason or diagnostic message for failure",
    )
    failure_classification: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
        comment="Classification of failure: transient or terminal",
    )

    # Relationships
    modules: Mapped[list["Module"]] = relationship(
        "Module",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact",
        back_populates="job",
        passive_deletes="all",
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun",
        back_populates="job",
        passive_deletes="all",
    )
    gates: Mapped[list["Gate"]] = relationship(
        "Gate",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    test_cases: Mapped[list["TestCase"]] = relationship(
        "TestCase",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        "AuditEvent",
        back_populates="job",
        passive_deletes="all",
    )
    source_provenance: Mapped["SourceProvenanceRecord | None"] = relationship(
        "SourceProvenanceRecord",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    model_executions: Mapped[list["ModelExecution"]] = relationship(
        "ModelExecution",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    budget_accounts: Mapped[list["BudgetAccount"]] = relationship(
        "BudgetAccount",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("version > 0", name="ck_job_version_positive"),
        CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', 'paused', 'failed', 'cancelled', 'completed', 'pending')",
            name="ck_job_lifecycle_status_allowed",
        ),
        Index("ix_job_status_created_at", "status", "created_at"),
        Index("ix_job_owner_created_at", "owner", "created_at"),
        Index("ix_job_tenant_owner", "tenant_id", "owner_user_id"),
        Index("ix_job_version", "id", "version"),
    )


__all__ = ["Job"]
