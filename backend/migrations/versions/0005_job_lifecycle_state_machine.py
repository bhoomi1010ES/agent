"""Add job lifecycle fields, concurrency version, and idempotency records.

Revision ID: 0005_job_lifecycle
Revises: 0004_auth_rbac_isolation
Create Date: 2026-10-16 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_job_lifecycle"
down_revision: str | None = "0004_auth_rbac_isolation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add versioning, lifecycle timestamps, failure diagnostics, and idempotency table."""
    # 1. Add new columns to job table
    op.add_column(
        "job",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "job",
        sa.Column("source_revision", sa.String(100), nullable=True),
    )
    op.add_column(
        "job",
        sa.Column("current_stage", sa.String(100), nullable=True),
    )
    op.add_column(
        "job",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job",
        sa.Column("failure_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "job",
        sa.Column("failure_classification", sa.String(50), nullable=True),
    )

    # 2. Update server default for job.status to queued
    op.alter_column("job", "status", server_default="queued")

    # 3. Add check constraints on job
    op.create_check_constraint(
        "ck_job_version_positive",
        "job",
        "version > 0",
    )
    op.create_check_constraint(
        "ck_job_lifecycle_status_allowed",
        "job",
        "status IN ('queued', 'running', 'awaiting_approval', 'paused', 'failed', 'cancelled', 'completed', 'pending')",
    )

    # 4. Add index on version
    op.create_index("ix_job_version", "job", ["id", "version"])

    # 5. Create idempotency_record table
    op.create_table(
        "idempotency_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=False),
        sa.Column(
            "response_body",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "action",
            "key",
            name="uq_idempotency_tenant_user_action_key",
        ),
    )
    op.create_index("ix_idempotency_record_tenant_id", "idempotency_record", ["tenant_id"])
    op.create_index("ix_idempotency_record_user_id", "idempotency_record", ["user_id"])
    op.create_index("ix_idempotency_record_expires_at", "idempotency_record", ["expires_at"])
    op.create_index(
        "ix_idempotency_lookup",
        "idempotency_record",
        ["tenant_id", "user_id", "action", "key"],
    )


def downgrade() -> None:
    """Revert lifecycle additions and idempotency persistence."""
    op.drop_index("ix_idempotency_lookup", table_name="idempotency_record")
    op.drop_index("ix_idempotency_record_expires_at", table_name="idempotency_record")
    op.drop_index("ix_idempotency_record_user_id", table_name="idempotency_record")
    op.drop_index("ix_idempotency_record_tenant_id", table_name="idempotency_record")
    op.drop_table("idempotency_record")

    op.drop_index("ix_job_version", table_name="job")
    op.drop_constraint("ck_job_lifecycle_status_allowed", "job", type_="check")
    op.drop_constraint("ck_job_version_positive", "job", type_="check")
    op.alter_column("job", "status", server_default="pending")

    op.drop_column("job", "failure_classification")
    op.drop_column("job", "failure_reason")
    op.drop_column("job", "failed_at")
    op.drop_column("job", "cancelled_at")
    op.drop_column("job", "completed_at")
    op.drop_column("job", "paused_at")
    op.drop_column("job", "started_at")
    op.drop_column("job", "current_stage")
    op.drop_column("job", "source_revision")
    op.drop_column("job", "version")
