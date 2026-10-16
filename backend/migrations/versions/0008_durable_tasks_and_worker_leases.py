"""Add durable background tasks and worker lease tracking table.

Revision ID: 0008_tasks_and_worker_leases
Revises: 0007_artifact_storage_lifecycle
Create Date: 2026-10-16 13:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_tasks_and_worker_leases"
down_revision: str | None = "0007_artifact_storage_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create task table with worker lease tracking, constraints, and query indexes."""
    op.create_table(
        "task",
        sa.Column("id", sa.UUID(), primary_key=True, comment="Unique task identifier"),
        sa.Column(
            "job_id",
            sa.UUID(),
            sa.ForeignKey("job.id", ondelete="CASCADE"),
            nullable=False,
            comment="Associated modernization job",
        ),
        sa.Column(
            "task_type",
            sa.String(100),
            nullable=False,
            comment="Durable task type or handler identifier",
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
            comment="Task status: pending, running, retry_wait, completed, failed, cancelled",
        ),
        sa.Column(
            "worker_id",
            sa.String(255),
            nullable=True,
            comment="Identifier of worker currently holding the lease",
        ),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the current worker lease expires",
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of times execution has been attempted",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="3",
            comment="Maximum allowed execution attempts",
        ),
        sa.Column(
            "retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Earliest UTC timestamp when task can be claimed after retry_wait",
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Task input payload or durable references",
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Task execution result payload or summary",
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
            comment="Error description from most recent failed attempt",
        ),
        sa.Column(
            "failure_classification",
            sa.String(100),
            nullable=True,
            comment="Classification of last failure determining retryability",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when task was first leased",
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when task reached terminal status",
        ),
        sa.Column(
            "workflow_thread_id",
            sa.String(255),
            nullable=True,
            comment="LangGraph workflow thread identifier if linked",
        ),
        sa.Column(
            "cancellation_reason",
            sa.Text(),
            nullable=True,
            comment="Reason provided when task was cancelled",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Record creation timestamp (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Record last update timestamp (UTC)",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_task_attempt_count_non_negative"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_task_max_attempts_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'retry_wait', 'completed', 'failed', 'cancelled')",
            name="ck_task_status_allowed",
        ),
    )

    op.create_index(
        "ix_task_claim_lookup",
        "task",
        ["status", "retry_at", "lease_expires_at", "created_at"],
    )
    op.create_index(
        "ix_task_recovery_lookup",
        "task",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "ix_task_job_status",
        "task",
        ["job_id", "status"],
    )
    op.create_index("ix_task_worker_id", "task", ["worker_id"])
    op.create_index("ix_task_task_type", "task", ["task_type"])
    op.create_index("ix_task_workflow_thread_id", "task", ["workflow_thread_id"])


def downgrade() -> None:
    """Drop task table and its associated indexes and constraints."""
    op.drop_index("ix_task_workflow_thread_id", table_name="task")
    op.drop_index("ix_task_task_type", table_name="task")
    op.drop_index("ix_task_worker_id", table_name="task")
    op.drop_index("ix_task_job_status", table_name="task")
    op.drop_index("ix_task_recovery_lookup", table_name="task")
    op.drop_index("ix_task_claim_lookup", table_name="task")
    op.drop_table("task")
