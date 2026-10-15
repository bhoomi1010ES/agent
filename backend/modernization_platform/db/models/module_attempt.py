"""SQLAlchemy ORM model for Module Attempt."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base, TimestampMixin
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.agent_run import AgentRun
    from modernization_platform.db.models.module import Module


class ModuleAttempt(Base, TimestampMixin):
    """Execution try by CodeWriter or repair loop on a module branch."""

    __tablename__ = "module_attempt"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique module attempt identifier",
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("module.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Target module being converted",
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Sequential try index (1, 2, 3...)",
    )
    branch: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Isolated module Git branch (e.g. job/<id>/<module>)",
    )
    commit_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Git commit hash created for this attempt",
    )
    outcome: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="in_progress",
        index=True,
        comment="Attempt status: in_progress, success, repair_needed, failed, escalated",
    )
    failure_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Diagnostic summary of why verification or review rejected this attempt",
    )
    tactic: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Conversion tactic applied: e.g. 7b_default, stronger_model, smaller_slice",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        comment="Timestamp when attempt completed (pass or fail)",
    )

    # Relationships
    module: Mapped["Module"] = relationship("Module", back_populates="attempts")
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun",
        back_populates="module_attempt",
    )

    __table_args__ = (
        UniqueConstraint(
            "module_id",
            "attempt_number",
            name="uq_module_attempt_number",
        ),
        Index("ix_module_attempt_outcome", "module_id", "outcome"),
    )
