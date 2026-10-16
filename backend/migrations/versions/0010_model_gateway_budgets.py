"""Create model_execution, budget_account, and budget_reservation tables.

Revision ID: 0010_model_gateway_budgets
Revises: 0009_human_gates_decisions
Create Date: 2026-10-16 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_model_gateway_budgets"
down_revision: str | None = "0009_human_gates_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create budget_account, budget_reservation, and model_execution tables with indexes."""
    # 1. Create budget_account table
    op.create_table(
        "budget_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("scope_type", sa.String(length=50), nullable=False, server_default="job"),
        sa.Column("scope_id", sa.String(length=100), nullable=False, server_default="job"),
        sa.Column("limit_microcents", sa.BigInteger(), nullable=False),
        sa.Column(
            "reserved_microcents", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("spent_microcents", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "warning_threshold_percent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("80"),
        ),
        sa.Column(
            "warning_emitted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("hard_stop_percent", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="USD"),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="active",
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("job_id", "scope_type", "scope_id", name="uq_budget_account_job_scope"),
        sa.CheckConstraint("reserved_microcents >= 0", name="ck_budget_reserved_non_negative"),
        sa.CheckConstraint("spent_microcents >= 0", name="ck_budget_spent_non_negative"),
        sa.CheckConstraint("limit_microcents >= 0", name="ck_budget_limit_non_negative"),
    )
    op.create_index("ix_budget_account_job_status", "budget_account", ["job_id", "status"])

    # 2. Create budget_reservation table
    op.create_table(
        "budget_reservation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "budget_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budget_account.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("agent_role", sa.String(length=100), nullable=False),
        sa.Column("reserved_microcents", sa.BigInteger(), nullable=False),
        sa.Column("actual_microcents", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="reserved",
            index=True,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reconciled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("reserved_microcents >= 0", name="ck_reservation_amount_non_negative"),
    )
    op.create_index(
        "ix_budget_res_account_status",
        "budget_reservation",
        ["budget_account_id", "status"],
    )
    op.create_index("ix_budget_res_job_status", "budget_reservation", ["job_id", "status"])

    # 3. Create model_execution table
    op.create_table(
        "model_execution",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("workflow_thread_id", sa.String(length=128), nullable=True),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("agent_role", sa.String(length=100), nullable=False, index=True),
        sa.Column("module", sa.String(length=100), nullable=True),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, index=True),
        sa.Column("model_id", sa.String(length=100), nullable=False, index=True),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "estimated_cost_microcents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "actual_cost_microcents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="success",
            index=True,
        ),
        sa.Column("failure_classification", sa.String(length=100), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "is_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("primary_provider", sa.String(length=50), nullable=True),
        sa.Column("primary_model_id", sa.String(length=100), nullable=True),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifact.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("artifact_version", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
    )
    op.create_index("ix_model_exec_job_created", "model_execution", ["job_id", "created_at"])
    op.create_index("ix_model_exec_provider_model", "model_execution", ["provider", "model_id"])
    op.create_index("ix_model_exec_agent_stage", "model_execution", ["agent_role", "stage"])


def downgrade() -> None:
    """Drop model_execution, budget_reservation, and budget_account tables."""
    op.drop_index("ix_model_exec_agent_stage", table_name="model_execution")
    op.drop_index("ix_model_exec_provider_model", table_name="model_execution")
    op.drop_index("ix_model_exec_job_created", table_name="model_execution")
    op.drop_table("model_execution")

    op.drop_index("ix_budget_res_job_status", table_name="budget_reservation")
    op.drop_index("ix_budget_res_account_status", table_name="budget_reservation")
    op.drop_table("budget_reservation")

    op.drop_index("ix_budget_account_job_status", table_name="budget_account")
    op.drop_table("budget_account")
