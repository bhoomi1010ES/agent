"""SQLAlchemy ORM model for Human-in-the-Loop Approval Gate."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.gate_decision import GateDecision
    from modernization_platform.db.models.job import Job


class Gate(Base):
    """Human-in-the-loop approval gate interrupt node (G1-G4 + Escalation)."""

    __tablename__ = "gate"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique gate instance identifier",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent modernization job",
    )
    gate_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Gate type: G1_FEASIBILITY, G2_CHARACTERIZATION, G3_BLUEPRINT_PLAN, G4_INTEGRATION_PR, ESCALATION",
    )
    state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="Gate state: pending, approved, rejected, timed_out, paused",
    )
    requested_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Timestamp when gate was opened and graph execution paused (UTC)",
    )
    artifact_versions_shown: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Snapshot of artifact identifiers and versions presented for human review",
    )
    needs_human_flags: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Specific questions, uncertainties, and risk items requiring human decision",
    )
    budget_used_cents: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Total job budget consumed at the moment gate opened",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        comment="Timestamp when human approver resolved this gate",
    )

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="gates")
    decisions: Mapped[list["GateDecision"]] = relationship(
        "GateDecision",
        back_populates="gate",
        cascade="all, delete-orphan",
        order_by="GateDecision.decided_at",
    )

    __table_args__ = (Index("ix_gate_job_type_state", "job_id", "gate_type", "state"),)
