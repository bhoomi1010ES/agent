"""Add durable human gate timeout, thread id, and append-only decision audit fields.

Revision ID: 0009_human_gates_decisions
Revises: 0008_tasks_and_worker_leases
Create Date: 2026-10-16 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_human_gates_decisions"
down_revision: str | None = "0008_tasks_and_worker_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add timeout, thread reference, diff reference, and enhanced audit fields."""
    # 1. Update gate table
    op.add_column(
        "gate",
        sa.Column(
            "timeout_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Timestamp when gate auto-pauses waiting for human decision (UTC)",
        ),
    )
    op.add_column(
        "gate",
        sa.Column(
            "workflow_thread_id",
            sa.String(length=128),
            nullable=True,
            comment="Associated LangGraph checkpoint thread identifier",
        ),
    )
    op.add_column(
        "gate",
        sa.Column(
            "artifact_diff_ref",
            sa.String(length=512),
            nullable=True,
            comment="Reference or diff URI presented to reviewers",
        ),
    )
    op.add_column(
        "gate",
        sa.Column(
            "resolved_by",
            sa.String(length=255),
            nullable=True,
            comment="Identity string of approver who resolved gate",
        ),
    )
    op.add_column(
        "gate",
        sa.Column(
            "resolved_by_user_id",
            sa.UUID(),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
            nullable=True,
            comment="Foreign key to user account of resolver",
        ),
    )
    op.add_column(
        "gate",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Timestamp of last gate state update",
        ),
    )
    op.create_index("ix_gate_timeout_at", "gate", ["timeout_at"])
    op.create_index("ix_gate_workflow_thread_id", "gate", ["workflow_thread_id"])
    op.create_index("ix_gate_pending_timeout", "gate", ["state", "timeout_at"])

    # 2. Update gate_decision table
    op.add_column(
        "gate_decision",
        sa.Column(
            "job_id",
            sa.UUID(),
            sa.ForeignKey("job.id", ondelete="CASCADE"),
            nullable=True,
            comment="Associated modernization job for direct audit queries",
        ),
    )
    op.add_column(
        "gate_decision",
        sa.Column(
            "gate_type",
            sa.String(length=50),
            nullable=True,
            comment="Type of gate at the time decision was rendered",
        ),
    )
    op.add_column(
        "gate_decision",
        sa.Column(
            "approver_role",
            sa.String(length=50),
            nullable=True,
            comment="Authoritative RBAC role of the approver at decision time",
        ),
    )
    op.add_column(
        "gate_decision",
        sa.Column(
            "artifact_version_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Authoritative snapshot of artifact versions reviewed at decision time",
        ),
    )
    op.add_column(
        "gate_decision",
        sa.Column(
            "artifact_diff_ref",
            sa.String(length=512),
            nullable=True,
            comment="Diff or external reference reviewed at decision time",
        ),
    )
    op.create_index("ix_gate_decision_job_id", "gate_decision", ["job_id"])
    op.create_index("ix_gate_decision_gate_type", "gate_decision", ["gate_type"])
    op.create_index(
        "ix_gate_decision_job_gate",
        "gate_decision",
        ["job_id", "gate_type", "decided_at"],
    )


def downgrade() -> None:
    """Revert gate and gate_decision enhancements."""
    op.drop_index("ix_gate_decision_job_gate", table_name="gate_decision")
    op.drop_index("ix_gate_decision_gate_type", table_name="gate_decision")
    op.drop_index("ix_gate_decision_job_id", table_name="gate_decision")
    op.drop_column("gate_decision", "artifact_diff_ref")
    op.drop_column("gate_decision", "artifact_version_refs")
    op.drop_column("gate_decision", "approver_role")
    op.drop_column("gate_decision", "gate_type")
    op.drop_column("gate_decision", "job_id")

    op.drop_index("ix_gate_pending_timeout", table_name="gate")
    op.drop_index("ix_gate_workflow_thread_id", table_name="gate")
    op.drop_index("ix_gate_timeout_at", table_name="gate")
    op.drop_column("gate", "updated_at")
    op.drop_column("gate", "resolved_by_user_id")
    op.drop_column("gate", "resolved_by")
    op.drop_column("gate", "artifact_diff_ref")
    op.drop_column("gate", "workflow_thread_id")
    op.drop_column("gate", "timeout_at")
