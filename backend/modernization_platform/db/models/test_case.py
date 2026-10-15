"""SQLAlchemy ORM model for Characterization Test Case."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base, ImmutableTimestampMixin
from modernization_platform.db.types import GUID

if TYPE_CHECKING:
    from modernization_platform.db.models.job import Job
    from modernization_platform.db.models.test_result import TestResult


class TestCase(Base, ImmutableTimestampMixin):
    """Characterization test case captured from legacy execution and frozen at Gate G2."""

    __test__ = False

    __tablename__ = "test_case"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique test case identifier",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Parent modernization job",
    )
    suite_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Frozen characterization suite version",
    )
    layer: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Test verification layer: unit, contract, data_effect, batch_output, ui_flow",
    )
    module_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Associated module name for slice testing",
    )
    legacy_capture_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Storage reference hash for captured input/output fixtures from legacy run",
    )
    normalization_rule_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Identifiers of normalization rules approved at G2 for nondeterminism",
    )
    captured_from: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="legacy_run",
        comment="Provenance of ground-truth outputs (strictly 'legacy_run')",
    )

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="test_cases")
    results: Mapped[list["TestResult"]] = relationship(
        "TestResult",
        back_populates="test_case",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_test_case_suite", "job_id", "suite_version"),
        Index("ix_test_case_module", "job_id", "module_name"),
    )
