"""Add source provenance persistence table for Git integration and reproducibility.

Revision ID: 0006_git_source_provenance
Revises: 0005_job_lifecycle
Create Date: 2026-10-16 11:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_git_source_provenance"
down_revision: str | None = "0005_job_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create source_provenance table linking jobs to reproducible Git commits and metadata."""
    op.create_table(
        "source_provenance",
        sa.Column("id", sa.UUID(), primary_key=True, comment="Unique source provenance identifier"),
        sa.Column(
            "job_id",
            sa.UUID(),
            sa.ForeignKey("job.id", ondelete="CASCADE"),
            nullable=False,
            comment="Associated modernization job",
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenant.id", ondelete="RESTRICT"),
            nullable=True,
            comment="Tenant authorization boundary",
        ),
        sa.Column(
            "repository_url",
            sa.Text(),
            nullable=False,
            comment="Validated HTTPS remote repository URL",
        ),
        sa.Column(
            "provider",
            sa.String(50),
            nullable=False,
            server_default="git",
            comment="VCS provider type",
        ),
        sa.Column(
            "requested_ref",
            sa.String(255),
            nullable=False,
            comment="User-specified branch, tag, or ref",
        ),
        sa.Column(
            "resolved_commit_sha",
            sa.String(64),
            nullable=False,
            comment="Exact 40-character Git commit hash",
        ),
        sa.Column(
            "branch",
            sa.String(255),
            nullable=True,
            comment="Remote branch name if known",
        ),
        sa.Column(
            "tree_hash",
            sa.String(64),
            nullable=True,
            comment="Git tree object hash",
        ),
        sa.Column(
            "commit_author",
            sa.String(255),
            nullable=True,
            comment="Commit author name",
        ),
        sa.Column(
            "commit_author_email",
            sa.String(255),
            nullable=True,
            comment="Commit author email",
        ),
        sa.Column(
            "commit_timestamp",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when commit was authored",
        ),
        sa.Column(
            "commit_message",
            sa.Text(),
            nullable=True,
            comment="Commit summary or subject",
        ),
        sa.Column(
            "file_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total files analyzed in checked-out source tree",
        ),
        sa.Column(
            "size_bytes",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total byte size of checked-out source tree",
        ),
        sa.Column(
            "repository_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Detailed repository structure and metadata",
        ),
        sa.Column(
            "provenance_hash",
            sa.String(64),
            nullable=False,
            comment="Content-addressed digest verifying reproducibility",
        ),
        sa.Column(
            "ingestion_status",
            sa.String(50),
            nullable=False,
            server_default="completed",
            comment="Status of source ingestion",
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Timestamp when source ingestion completed",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Record creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Record last updated timestamp",
        ),
        sa.UniqueConstraint("job_id", name="uq_source_provenance_job_id"),
    )

    op.create_index("ix_source_provenance_job_id", "source_provenance", ["job_id"])
    op.create_index("ix_source_provenance_commit_sha", "source_provenance", ["resolved_commit_sha"])
    op.create_index(
        "ix_source_provenance_tenant_created", "source_provenance", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    """Drop source_provenance table and its indexes."""
    op.drop_index("ix_source_provenance_tenant_created", table_name="source_provenance")
    op.drop_index("ix_source_provenance_commit_sha", table_name="source_provenance")
    op.drop_index("ix_source_provenance_job_id", table_name="source_provenance")
    op.drop_table("source_provenance")
