"""SQLAlchemy ORM model for immutable modernization Artifact."""

import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base, ImmutableTimestampMixin
from modernization_platform.db.types import GUID

if TYPE_CHECKING:
    from modernization_platform.db.models.agent_run import AgentRun
    from modernization_platform.db.models.job import Job


class ArtifactStatus(enum.StrEnum):
    """Artifact storage and lifecycle status states."""

    PENDING = "pending"
    UPLOADING = "uploading"
    AVAILABLE = "available"
    FAILED = "failed"
    DELETED = "deleted"


class Artifact(Base, ImmutableTimestampMixin):
    """Immutable, content-addressed artifact representing typed outputs of agent runs."""

    __tablename__ = "artifact"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique artifact identifier",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Parent modernization job",
    )
    type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Artifact schema type (e.g. RepoInventory, TargetBlueprint, ChangeSet)",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Monotonically increasing version number for this artifact type in this job",
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 hash of the artifact payload",
    )
    storage_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Content-addressed object storage reference key",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ArtifactStatus.AVAILABLE.value,
        server_default=ArtifactStatus.AVAILABLE.value,
        comment="Artifact lifecycle status (pending, uploading, available, failed, deleted)",
    )
    size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Total artifact byte size in object storage",
    )
    content_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default="application/json",
        server_default="application/json",
        comment="MIME/content type of stored artifact",
    )
    produced_by_run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("agent_run.id", ondelete="SET NULL"),
        nullable=True,
        comment="Agent run that produced this artifact version",
    )
    derived_from: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="List of artifact UUID strings this artifact was derived from (full lineage)",
    )
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Supplementary metadata: needs_human flag, uncertainties, schema version",
    )

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="artifacts")
    producer_run: Mapped["AgentRun | None"] = relationship(
        "AgentRun",
        foreign_keys=[produced_by_run_id],
        back_populates="produced_artifacts",
    )

    __table_args__ = (
        CheckConstraint("version > 0", name="version_positive"),
        UniqueConstraint(
            "job_id",
            "type",
            "version",
            name="uq_artifact_job_type_version",
        ),
        Index("ix_artifact_job_type", "job_id", "type"),
        Index("ix_artifact_content_hash", "content_hash"),
        Index("ix_artifact_status", "status"),
        Index("ix_artifact_job_id_status", "job_id", "status"),
    )
