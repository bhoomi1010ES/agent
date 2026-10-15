"""Initial persistence schema creating core modernization platform entities.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-10-15 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. job table
    op.create_table(
        "job",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique job identifier"),
        sa.Column("owner", sa.String(255), nullable=False, comment="Owner user or organization"),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
            comment="Lifecycle status",
        ),
        sa.Column("source_ref", sa.Text(), nullable=False, comment="Source repo URL or commit"),
        sa.Column(
            "target_stack_spec",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Target stack spec",
        ),
        sa.Column(
            "budget",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Budget thresholds",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Created timestamp (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Updated timestamp (UTC)",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Finished timestamp (UTC)",
        ),
    )
    op.create_index("ix_job_owner", "job", ["owner"])
    op.create_index("ix_job_status", "job", ["status"])
    op.create_index("ix_job_status_created_at", "job", ["status", "created_at"])
    op.create_index("ix_job_owner_created_at", "job", ["owner", "created_at"])

    # 2. module table
    op.create_table(
        "module",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique module identifier"),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("job.id", ondelete="CASCADE"),
            nullable=False,
            comment="Parent job",
        ),
        sa.Column("name", sa.String(255), nullable=False, comment="Module name"),
        sa.Column(
            "legacy_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Legacy file paths",
        ),
        sa.Column(
            "depends_on",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Module dependencies",
        ),
        sa.Column(
            "risk_score",
            sa.Float(),
            nullable=False,
            server_default="0.0",
            comment="Complexity score",
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
            comment="Conversion status",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Created timestamp (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Updated timestamp (UTC)",
        ),
        sa.UniqueConstraint("job_id", "name", name="uq_module_job_id_name"),
    )
    op.create_index("ix_module_job_id", "module", ["job_id"])
    op.create_index("ix_module_status", "module", ["status"])
    op.create_index("ix_module_job_status", "module", ["job_id", "status"])

    # 3. module_attempt table
    op.create_table(
        "module_attempt",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique attempt identifier"),
        sa.Column(
            "module_id",
            sa.String(36),
            sa.ForeignKey("module.id", ondelete="CASCADE"),
            nullable=False,
            comment="Target module",
        ),
        sa.Column(
            "attempt_number", sa.Integer(), nullable=False, comment="Sequential attempt index"
        ),
        sa.Column("branch", sa.String(255), nullable=False, comment="Module Git branch"),
        sa.Column("commit_hash", sa.String(64), nullable=True, comment="Git commit hash"),
        sa.Column(
            "outcome",
            sa.String(50),
            nullable=False,
            server_default="in_progress",
            comment="Attempt status",
        ),
        sa.Column("failure_summary", sa.Text(), nullable=True, comment="Failure summary"),
        sa.Column("tactic", sa.String(100), nullable=True, comment="Conversion tactic"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Created timestamp (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Updated timestamp (UTC)",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Finished timestamp (UTC)",
        ),
        sa.UniqueConstraint("module_id", "attempt_number", name="uq_module_attempt_number"),
    )
    op.create_index("ix_module_attempt_module_id", "module_attempt", ["module_id"])
    op.create_index("ix_module_attempt_outcome", "module_attempt", ["module_id", "outcome"])

    # 4. agent_run table
    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique run identifier"),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("job.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Parent job",
        ),
        sa.Column(
            "module_attempt_id",
            sa.String(36),
            sa.ForeignKey("module_attempt.id", ondelete="SET NULL"),
            nullable=True,
            comment="Module attempt",
        ),
        sa.Column("agent", sa.String(100), nullable=False, comment="Agent identifier"),
        sa.Column("step_key", sa.String(100), nullable=True, comment="Idempotency step key"),
        sa.Column("model", sa.String(100), nullable=False, comment="Model utilized"),
        sa.Column(
            "prompt_version", sa.String(50), nullable=False, comment="Prompt template version"
        ),
        sa.Column(
            "input_artifact_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Input artifact IDs",
        ),
        sa.Column(
            "output_artifact_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Output artifact IDs",
        ),
        sa.Column(
            "tokens_input", sa.Integer(), nullable=False, server_default="0", comment="Input tokens"
        ),
        sa.Column(
            "tokens_output",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Output tokens",
        ),
        sa.Column(
            "cost_cents", sa.Float(), nullable=False, server_default="0.0", comment="Cost in cents"
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Duration in ms",
        ),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Tool execution trace",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, comment="Run timestamp (UTC)"
        ),
        sa.UniqueConstraint("job_id", "agent", "step_key", name="uq_agent_run_idempotency"),
    )
    op.create_index("ix_agent_run_job_id", "agent_run", ["job_id"])
    op.create_index("ix_agent_run_module_attempt_id", "agent_run", ["module_attempt_id"])
    op.create_index("ix_agent_run_agent", "agent_run", ["agent"])
    op.create_index("ix_agent_run_job_agent", "agent_run", ["job_id", "agent"])
    op.create_index("ix_agent_run_step_key", "agent_run", ["step_key"])

    # 5. artifact table
    op.create_table(
        "artifact",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique artifact identifier"),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("job.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Parent job",
        ),
        sa.Column("type", sa.String(100), nullable=False, comment="Artifact schema type"),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1", comment="Version index"
        ),
        sa.Column("content_hash", sa.String(64), nullable=False, comment="SHA-256 hash"),
        sa.Column("storage_ref", sa.Text(), nullable=False, comment="Storage reference key"),
        sa.Column(
            "produced_by_run_id",
            sa.String(36),
            sa.ForeignKey("agent_run.id", ondelete="SET NULL"),
            nullable=True,
            comment="Producing run",
        ),
        sa.Column(
            "derived_from",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Derived artifact IDs",
        ),
        sa.Column(
            "artifact_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Metadata payload",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Created timestamp (UTC)",
        ),
        sa.UniqueConstraint("job_id", "type", "version", name="uq_artifact_job_type_version"),
    )
    op.create_index("ix_artifact_job_id", "artifact", ["job_id"])
    op.create_index("ix_artifact_type", "artifact", ["type"])
    op.create_index("ix_artifact_job_type", "artifact", ["job_id", "type"])
    op.create_index("ix_artifact_content_hash", "artifact", ["content_hash"])

    # 6. test_case table
    op.create_table(
        "test_case",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique test case identifier"),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("job.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Parent job",
        ),
        sa.Column(
            "suite_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Frozen suite version",
        ),
        sa.Column("layer", sa.String(50), nullable=False, comment="Verification layer"),
        sa.Column("module_name", sa.String(255), nullable=True, comment="Module name"),
        sa.Column(
            "legacy_capture_ref", sa.Text(), nullable=False, comment="Legacy capture reference"
        ),
        sa.Column(
            "normalization_rule_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Normalization rule IDs",
        ),
        sa.Column(
            "captured_from",
            sa.String(50),
            nullable=False,
            server_default="legacy_run",
            comment="Output provenance",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Created timestamp (UTC)",
        ),
    )
    op.create_index("ix_test_case_job_id", "test_case", ["job_id"])
    op.create_index("ix_test_case_module_name", "test_case", ["module_name"])
    op.create_index("ix_test_case_suite", "test_case", ["job_id", "suite_version"])
    op.create_index("ix_test_case_module", "test_case", ["job_id", "module_name"])

    # 7. test_result table
    op.create_table(
        "test_result",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique test result identifier"),
        sa.Column(
            "test_case_id",
            sa.String(36),
            sa.ForeignKey("test_case.id", ondelete="CASCADE"),
            nullable=False,
            comment="Associated test case",
        ),
        sa.Column("system", sa.String(50), nullable=False, comment="legacy or converted"),
        sa.Column("run_id", sa.String(36), nullable=True, comment="Run identifier"),
        sa.Column("outcome", sa.String(50), nullable=False, comment="Execution outcome"),
        sa.Column("diff_summary", sa.Text(), nullable=True, comment="Diff summary"),
        sa.Column("failure_class", sa.String(50), nullable=True, comment="Failure classification"),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Execution timestamp (UTC)",
        ),
    )
    op.create_index("ix_test_result_test_case_id", "test_result", ["test_case_id"])
    op.create_index("ix_test_result_outcome", "test_result", ["outcome"])
    op.create_index("ix_test_result_failure_class", "test_result", ["failure_class"])
    op.create_index("ix_test_result_lookup", "test_result", ["test_case_id", "system", "outcome"])

    # 8. gate table
    op.create_table(
        "gate",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique gate identifier"),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("job.id", ondelete="CASCADE"),
            nullable=False,
            comment="Parent job",
        ),
        sa.Column("gate_type", sa.String(50), nullable=False, comment="Gate type"),
        sa.Column(
            "state", sa.String(50), nullable=False, server_default="pending", comment="Gate state"
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Requested timestamp (UTC)",
        ),
        sa.Column(
            "artifact_versions_shown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Artifact versions shown",
        ),
        sa.Column(
            "needs_human_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Human review flags",
        ),
        sa.Column(
            "budget_used_cents",
            sa.Float(),
            nullable=False,
            server_default="0.0",
            comment="Budget used in cents",
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Resolved timestamp (UTC)",
        ),
    )
    op.create_index("ix_gate_job_id", "gate", ["job_id"])
    op.create_index("ix_gate_type", "gate", ["gate_type"])
    op.create_index("ix_gate_state", "gate", ["state"])
    op.create_index("ix_gate_job_type_state", "gate", ["job_id", "gate_type", "state"])

    # 9. gate_decision table
    op.create_table(
        "gate_decision",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique decision identifier"),
        sa.Column(
            "gate_id",
            sa.String(36),
            sa.ForeignKey("gate.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Target gate",
        ),
        sa.Column("actor", sa.String(255), nullable=False, comment="Decision-maker actor"),
        sa.Column("decision", sa.String(50), nullable=False, comment="Decision outcome"),
        sa.Column("feedback", sa.Text(), nullable=True, comment="Rejection feedback"),
        sa.Column(
            "waivers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Waiver rationale",
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Decision timestamp (UTC)",
        ),
    )
    op.create_index("ix_gate_decision_gate_id", "gate_decision", ["gate_id"])
    op.create_index("ix_gate_decision_actor", "gate_decision", ["actor", "decided_at"])

    # 10. audit_event table
    op.create_table(
        "audit_event",
        sa.Column("id", sa.String(36), primary_key=True, comment="Unique audit event identifier"),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("job.id", ondelete="SET NULL"),
            nullable=True,
            comment="Parent job",
        ),
        sa.Column("actor", sa.String(255), nullable=False, comment="Actor identity"),
        sa.Column("action", sa.String(100), nullable=False, comment="Action name"),
        sa.Column("correlation_id", sa.String(64), nullable=True, comment="Request correlation ID"),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Event payload",
        ),
        sa.Column(
            "event_time",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Event timestamp (UTC)",
        ),
        sa.Column(
            "event_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Event format version",
        ),
    )
    op.create_index("ix_audit_event_job_id", "audit_event", ["job_id"])
    op.create_index("ix_audit_event_actor", "audit_event", ["actor"])
    op.create_index("ix_audit_event_action", "audit_event", ["action"])
    op.create_index("ix_audit_event_correlation_id", "audit_event", ["correlation_id"])
    op.create_index("ix_audit_event_event_time", "audit_event", ["event_time"])
    op.create_index("ix_audit_event_job_time", "audit_event", ["job_id", "event_time"])
    op.create_index("ix_audit_event_action_time", "audit_event", ["action", "event_time"])


def downgrade() -> None:
    # Drop tables in reverse order of foreign key dependency
    op.drop_table("audit_event")
    op.drop_table("gate_decision")
    op.drop_table("gate")
    op.drop_table("test_result")
    op.drop_table("test_case")
    op.drop_table("artifact")
    op.drop_table("agent_run")
    op.drop_table("module_attempt")
    op.drop_table("module")
    op.drop_table("job")
