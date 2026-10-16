"""SQLAlchemy ORM model for Gate Decision."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.gate import Gate
    from modernization_platform.db.models.identity import UserAccount
    from modernization_platform.db.models.job import Job


class GateDecision(Base):
    """Immutable, append-only record of a human approval, rejection, or waiver at a gate."""

    __tablename__ = "gate_decision"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique gate decision identifier",
    )
    gate_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("gate.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Target approval gate",
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Associated modernization job for direct audit queries",
    )
    gate_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Type of gate at the time decision was rendered",
    )
    actor: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Identity of human decision-maker (email or user ID)",
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("user_account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Stable authenticated actor; null only for legacy/system decisions",
    )
    approver_role: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Authoritative RBAC role of the approver at decision time",
    )
    decision: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Resolution decision: approved, rejected, waived",
    )
    feedback: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Mandatory feedback when decision is rejected; optional rationale otherwise",
    )
    waivers: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Structured waiver reason and approved variance metadata",
    )
    artifact_version_refs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Authoritative snapshot of artifact versions reviewed at decision time",
    )
    artifact_diff_ref: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Diff or external reference reviewed at decision time",
    )
    decided_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Timestamp when decision was submitted (UTC)",
    )

    # Relationships
    gate: Mapped["Gate"] = relationship("Gate", back_populates="decisions")
    job: Mapped["Job | None"] = relationship("Job")
    actor_user: Mapped["UserAccount | None"] = relationship(
        "UserAccount",
        foreign_keys=[actor_user_id],
    )

    __table_args__ = (
        Index("ix_gate_decision_actor", "actor", "decided_at"),
        Index("ix_gate_decision_job_gate", "job_id", "gate_type", "decided_at"),
    )
