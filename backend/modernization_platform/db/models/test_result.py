"""SQLAlchemy ORM model for Verification Test Result."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.test_case import TestCase


class TestResult(Base):
    """Test verification execution outcome produced deterministically by the Verifier."""

    __test__ = False

    __tablename__ = "test_result"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique test execution result identifier",
    )
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Associated frozen test case",
    )
    system: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Target of test run: legacy or converted",
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        nullable=True,
        index=True,
        comment="Identifier of the executing run or module attempt",
    )
    outcome: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Execution result: pass, fail, error, skipped",
    )
    diff_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Structured difference summary if failure occurred",
    )
    failure_class: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Deterministic classification: Regression, IntendedDifference, Nondeterministic, TestDefect",
    )
    executed_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Timestamp when test verification executed (UTC)",
    )

    # Relationships
    test_case: Mapped["TestCase"] = relationship("TestCase", back_populates="results")

    __table_args__ = (Index("ix_test_result_lookup", "test_case_id", "system", "outcome"),)
