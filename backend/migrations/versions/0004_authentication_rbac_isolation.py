"""Add tenant identity, RBAC membership, sessions, and resource ownership.

Revision ID: 0004_auth_rbac_isolation
Revises: 0003_native_uuid_columns
Create Date: 2026-10-15 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_auth_rbac_isolation"
down_revision: str | None = "0003_native_uuid_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create identity boundaries while preserving unassigned historical jobs."""
    op.create_table(
        "tenant",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_tenant_slug"),
    )
    op.create_table(
        "user_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.String(500), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_user_account_issuer_subject"),
    )
    op.create_table(
        "tenant_membership",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'reviewer', 'approver', 'admin')",
            name="role_allowed",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership_tenant_user"),
    )
    op.create_index("ix_tenant_membership_tenant_id", "tenant_membership", ["tenant_id"])
    op.create_index("ix_tenant_membership_user_id", "tenant_membership", ["user_id"])
    op.create_index(
        "ix_tenant_membership_lookup",
        "tenant_membership",
        ["tenant_id", "user_id", "active"],
    )

    op.create_table(
        "auth_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id_hash", sa.String(64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authentication_method", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_id_hash", name="uq_auth_session_token_id_hash"),
    )
    op.create_index("ix_auth_session_user_id", "auth_session", ["user_id"])
    op.create_index("ix_auth_session_tenant_id", "auth_session", ["tenant_id"])
    op.create_index("ix_auth_session_expires_at", "auth_session", ["expires_at"])
    op.create_index(
        "ix_auth_session_active", "auth_session", ["tenant_id", "user_id", "revoked_at"]
    )

    op.add_column("job", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("job", sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_job_tenant_id_tenant", "job", "tenant", ["tenant_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_job_owner_user_id_user_account",
        "job",
        "user_account",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_job_tenant_id", "job", ["tenant_id"])
    op.create_index("ix_job_owner_user_id", "job", ["owner_user_id"])
    op.create_index("ix_job_tenant_owner", "job", ["tenant_id", "owner_user_id"])

    op.create_table(
        "job_member",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["membership_id"], ["tenant_membership.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "membership_id", name="uq_job_member_job_membership"),
    )
    op.create_index("ix_job_member_job_id", "job_member", ["job_id"])
    op.create_index("ix_job_member_membership_id", "job_member", ["membership_id"])

    op.add_column(
        "gate_decision",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_gate_decision_actor_user_id_user_account",
        "gate_decision",
        "user_account",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_gate_decision_actor_user_id", "gate_decision", ["actor_user_id"])

    op.add_column(
        "audit_event",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_audit_event_actor_user_id_user_account",
        "audit_event",
        "user_account",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_audit_event_actor_user_id", "audit_event", ["actor_user_id"])


def downgrade() -> None:
    """Remove authentication structures without altering earlier migration history."""
    op.drop_index("ix_audit_event_actor_user_id", table_name="audit_event")
    op.drop_constraint(
        "fk_audit_event_actor_user_id_user_account", "audit_event", type_="foreignkey"
    )
    op.drop_column("audit_event", "actor_user_id")
    op.drop_index("ix_gate_decision_actor_user_id", table_name="gate_decision")
    op.drop_constraint(
        "fk_gate_decision_actor_user_id_user_account", "gate_decision", type_="foreignkey"
    )
    op.drop_column("gate_decision", "actor_user_id")
    op.drop_table("job_member")
    op.drop_index("ix_job_tenant_owner", table_name="job")
    op.drop_index("ix_job_owner_user_id", table_name="job")
    op.drop_index("ix_job_tenant_id", table_name="job")
    op.drop_constraint("fk_job_owner_user_id_user_account", "job", type_="foreignkey")
    op.drop_constraint("fk_job_tenant_id_tenant", "job", type_="foreignkey")
    op.drop_column("job", "owner_user_id")
    op.drop_column("job", "tenant_id")
    op.drop_table("auth_session")
    op.drop_table("tenant_membership")
    op.drop_table("user_account")
    op.drop_table("tenant")
