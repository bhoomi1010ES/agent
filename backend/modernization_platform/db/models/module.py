"""SQLAlchemy ORM model for modernization Module."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base, TimestampMixin
from modernization_platform.db.types import GUID

if TYPE_CHECKING:
    from modernization_platform.db.models.job import Job
    from modernization_platform.db.models.module_attempt import ModuleAttempt


class Module(Base, TimestampMixin):
    """Conversion unit in the DAG representing a cohesive slice of the legacy system."""

    __tablename__ = "module"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique module identifier",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent modernization job",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Unique module name within the conversion plan",
    )
    legacy_paths: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="List of source file paths in legacy repo belonging to this module",
    )
    depends_on: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="List of module names this module depends on (DAG edges)",
    )
    risk_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Deterministic complexity and risk score",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="Conversion status: pending, in_progress, converted, failed, escalated",
    )

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="modules")
    attempts: Mapped[list["ModuleAttempt"]] = relationship(
        "ModuleAttempt",
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="ModuleAttempt.attempt_number",
    )

    __table_args__ = (
        UniqueConstraint("job_id", "name", name="uq_module_job_id_name"),
        Index("ix_module_job_status", "job_id", "status"),
    )
