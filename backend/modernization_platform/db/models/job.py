"""SQLAlchemy ORM model for modernization Job."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base, TimestampMixin
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.agent_run import AgentRun
    from modernization_platform.db.models.artifact import Artifact
    from modernization_platform.db.models.audit_event import AuditEvent
    from modernization_platform.db.models.gate import Gate
    from modernization_platform.db.models.module import Module
    from modernization_platform.db.models.test_case import TestCase


class Job(Base, TimestampMixin):
    """Modernization execution job tracking lifecycle, budget, and artifacts."""

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
        default="pending",
        index=True,
        comment="Lifecycle status: pending, running, paused, completed, failed",
    )
    source_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Source repository URL, Git commit hash, or path",
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
    finished_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        comment="Timestamp when job reached terminal state",
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

    __table_args__ = (
        Index("ix_job_status_created_at", "status", "created_at"),
        Index("ix_job_owner_created_at", "owner", "created_at"),
        Index("ix_job_tenant_owner", "tenant_id", "owner_user_id"),
    )
