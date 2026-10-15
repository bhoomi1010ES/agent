"""Align migrated identifier columns with the ORM's native PostgreSQL UUID type.

Revision ID: 0003_native_uuid_columns
Revises: 0002_positive_constraints
Create Date: 2026-10-15 15:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_native_uuid_columns"
down_revision: str | None = "0002_positive_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOREIGN_KEYS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("fk_agent_run_job_id_job", "agent_run", "job_id", "job", "id", "RESTRICT"),
    (
        "fk_agent_run_module_attempt_id_module_attempt",
        "agent_run",
        "module_attempt_id",
        "module_attempt",
        "id",
        "SET NULL",
    ),
    ("fk_artifact_job_id_job", "artifact", "job_id", "job", "id", "RESTRICT"),
    (
        "fk_artifact_produced_by_run_id_agent_run",
        "artifact",
        "produced_by_run_id",
        "agent_run",
        "id",
        "SET NULL",
    ),
    ("fk_audit_event_job_id_job", "audit_event", "job_id", "job", "id", "SET NULL"),
    ("fk_gate_job_id_job", "gate", "job_id", "job", "id", "CASCADE"),
    (
        "fk_gate_decision_gate_id_gate",
        "gate_decision",
        "gate_id",
        "gate",
        "id",
        "RESTRICT",
    ),
    ("fk_module_job_id_job", "module", "job_id", "job", "id", "CASCADE"),
    (
        "fk_module_attempt_module_id_module",
        "module_attempt",
        "module_id",
        "module",
        "id",
        "CASCADE",
    ),
    ("fk_test_case_job_id_job", "test_case", "job_id", "job", "id", "RESTRICT"),
    (
        "fk_test_result_test_case_id_test_case",
        "test_result",
        "test_case_id",
        "test_case",
        "id",
        "CASCADE",
    ),
)

_UUID_COLUMNS: tuple[tuple[str, str], ...] = (
    ("job", "id"),
    ("module", "id"),
    ("module", "job_id"),
    ("module_attempt", "id"),
    ("module_attempt", "module_id"),
    ("agent_run", "id"),
    ("agent_run", "job_id"),
    ("agent_run", "module_attempt_id"),
    ("artifact", "id"),
    ("artifact", "job_id"),
    ("artifact", "produced_by_run_id"),
    ("test_case", "id"),
    ("test_case", "job_id"),
    ("test_result", "id"),
    ("test_result", "test_case_id"),
    ("test_result", "run_id"),
    ("gate", "id"),
    ("gate", "job_id"),
    ("gate_decision", "id"),
    ("gate_decision", "gate_id"),
    ("audit_event", "id"),
    ("audit_event", "job_id"),
)


def _drop_foreign_keys() -> None:
    for name, table, _column, _target, _target_column, _ondelete in _FOREIGN_KEYS:
        op.drop_constraint(name, table, type_="foreignkey")


def _create_foreign_keys() -> None:
    for name, table, column, target, target_column, ondelete in _FOREIGN_KEYS:
        op.create_foreign_key(
            name,
            table,
            target,
            [column],
            [target_column],
            ondelete=ondelete,
        )


def upgrade() -> None:
    """Convert legacy string identifiers to native UUID columns."""
    _drop_foreign_keys()
    for table, column in _UUID_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length=36),
            type_=postgresql.UUID(as_uuid=True),
            postgresql_using=f"{column}::uuid",
        )
    _create_foreign_keys()


def downgrade() -> None:
    """Restore the original string identifier representation."""
    _drop_foreign_keys()
    for table, column in reversed(_UUID_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=postgresql.UUID(as_uuid=True),
            type_=sa.String(length=36),
            postgresql_using=f"{column}::text",
        )
    _create_foreign_keys()
