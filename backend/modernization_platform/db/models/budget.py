"""SQLAlchemy ORM models for durable budget accounts and atomic reservation coordination."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.job import Job


class BudgetAccount(Base):
    """Durable budget account tracking financial thresholds, reservations, and spend."""

    __tablename__ = "budget_account"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique budget account identifier",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Associated modernization job",
    )
    scope_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="job",
        comment="Budget scope category: job, module, tenant, agent",
    )
    scope_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="job",
        comment="Scope discriminator (e.g. 'job' or module identifier)",
    )
    limit_microcents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Configured spending ceiling in integer microcents",
    )
    reserved_microcents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="Total in-flight budget reservations in integer microcents",
    )
    spent_microcents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="Total reconciled actual expenditure in integer microcents",
    )
    warning_threshold_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=80,
        comment="Percentage threshold triggering warning event (default 80%)",
    )
    warning_emitted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True if 80% warning has already been emitted for this budget",
    )
    hard_stop_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        comment="Percentage threshold enforcing hard stop (default 100%)",
    )
    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="USD",
        comment="Currency code (default USD)",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        index=True,
        comment="Budget status: active, warning, exhausted, closed",
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Timestamp when budget account was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        comment="Timestamp when budget was last adjusted or reconciled",
    )

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="budget_accounts")
    reservations: Mapped[list["BudgetReservation"]] = relationship(
        "BudgetReservation",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "scope_type",
            "scope_id",
            name="uq_budget_account_job_scope",
        ),
        CheckConstraint("reserved_microcents >= 0", name="ck_budget_reserved_non_negative"),
        CheckConstraint("spent_microcents >= 0", name="ck_budget_spent_non_negative"),
        CheckConstraint("limit_microcents >= 0", name="ck_budget_limit_non_negative"),
        Index("ix_budget_account_job_status", "job_id", "status"),
    )

    @property
    def available_microcents(self) -> int:
        """Remaining unreserved and unspent microcents."""
        return max(0, self.limit_microcents - (self.spent_microcents + self.reserved_microcents))

    @property
    def spend_ratio(self) -> float:
        """Ratio of spent to limit (0.0 to 1.0+)."""
        if self.limit_microcents <= 0:
            return 1.0
        return self.spent_microcents / self.limit_microcents


class BudgetReservation(Base):
    """In-flight atomic cost reservation holding budget for an active model call."""

    __tablename__ = "budget_reservation"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique reservation identifier",
    )
    budget_account_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("budget_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent budget account",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent modernization job",
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("task.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional background task boundary",
    )
    agent_role: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Agent role requesting reservation",
    )
    reserved_microcents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Estimated amount reserved in integer microcents",
    )
    actual_microcents: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Actual expenditure recorded upon reconciliation",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="reserved",
        index=True,
        comment="Reservation status: reserved, reconciled, released, expired",
    )
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        index=True,
        comment="Timestamp when un-reconciled reservation expires",
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Timestamp when reservation was acquired",
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        comment="Timestamp when actual usage was reconciled or released",
    )

    # Relationships
    account: Mapped["BudgetAccount"] = relationship("BudgetAccount", back_populates="reservations")

    __table_args__ = (
        CheckConstraint("reserved_microcents >= 0", name="ck_reservation_amount_non_negative"),
        Index("ix_budget_res_account_status", "budget_account_id", "status"),
        Index("ix_budget_res_job_status", "job_id", "status"),
    )


__all__ = ["BudgetAccount", "BudgetReservation"]
