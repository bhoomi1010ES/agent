"""SQLAlchemy ORM model for Job Source Provenance."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base, TimestampMixin
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.job import Job


class SourceProvenanceRecord(Base, TimestampMixin):
    """Immutable, auditable source code provenance and metadata captured for a Job."""

    __tablename__ = "source_provenance"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique source provenance identifier",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="Associated modernization job",
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Tenant authorization boundary",
    )
    repository_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Validated HTTPS remote repository URL",
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="git",
        comment="VCS provider type (e.g. git, github, gitlab)",
    )
    requested_ref: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="User-specified branch, tag, or ref",
    )
    resolved_commit_sha: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Exact 40-character Git commit hash",
    )
    branch: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Remote branch name if known",
    )
    tree_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Git tree object hash representing directory content",
    )
    commit_author: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Commit author name",
    )
    commit_author_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Commit author email",
    )
    commit_timestamp: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        comment="Timestamp when commit was authored",
    )
    commit_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Commit summary or subject",
    )
    file_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total files analyzed in checked-out source tree",
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total byte size of checked-out source tree",
    )
    repository_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Detailed repository structure, language, or branch metadata",
    )
    provenance_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Content-addressed digest verifying reproducibility",
    )
    ingestion_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="completed",
        comment="Status of source ingestion: completed, failed, pending",
    )
    ingested_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        comment="Timestamp when source ingestion completed",
    )

    # Relationships
    job: Mapped["Job"] = relationship(
        "Job",
        back_populates="source_provenance",
    )

    __table_args__ = (
        Index("ix_source_provenance_commit_sha", "resolved_commit_sha"),
        Index("ix_source_provenance_tenant_created", "tenant_id", "created_at"),
    )


__all__ = ["SourceProvenanceRecord"]
