"""Add artifact storage lifecycle, status, size, and content type metadata.

Revision ID: 0007_artifact_storage_lifecycle
Revises: 0006_git_source_provenance
Create Date: 2026-10-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_artifact_storage_lifecycle"
down_revision: str | None = "0006_git_source_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add status, size_bytes, and content_type columns with indexes to artifact table."""
    op.add_column(
        "artifact",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="available",
            comment="Artifact lifecycle status (pending, uploading, available, failed, deleted)",
        ),
    )
    op.add_column(
        "artifact",
        sa.Column(
            "size_bytes",
            sa.BigInteger(),
            nullable=True,
            comment="Total artifact byte size in object storage",
        ),
    )
    op.add_column(
        "artifact",
        sa.Column(
            "content_type",
            sa.String(length=255),
            nullable=True,
            server_default="application/json",
            comment="MIME/content type of stored artifact",
        ),
    )
    op.create_index("ix_artifact_status", "artifact", ["status"], unique=False)
    op.create_index("ix_artifact_job_id_status", "artifact", ["job_id", "status"], unique=False)


def downgrade() -> None:
    """Drop lifecycle status, size, and content_type columns and indexes from artifact table."""
    op.drop_index("ix_artifact_job_id_status", table_name="artifact")
    op.drop_index("ix_artifact_status", table_name="artifact")
    op.drop_column("artifact", "content_type")
    op.drop_column("artifact", "size_bytes")
    op.drop_column("artifact", "status")
