"""Add documented positive version and attempt-number constraints.

Revision ID: 0002_positive_constraints
Revises: 0001_initial_schema
Create Date: 2026-10-15 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_positive_constraints"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enforce the positive counters specified by the Phase 01.2 schema."""
    op.create_check_constraint(
        "version_positive",
        "artifact",
        "version > 0",
    )
    op.create_check_constraint(
        "number_positive",
        "module_attempt",
        "attempt_number > 0",
    )


def downgrade() -> None:
    """Remove the positive counter constraints."""
    op.drop_constraint(
        "number_positive",
        "module_attempt",
        type_="check",
    )
    op.drop_constraint(
        "version_positive",
        "artifact",
        type_="check",
    )
