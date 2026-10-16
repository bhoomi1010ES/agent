"""SQLAlchemy repository for durable budget accounts and atomic reservation coordination."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.core.exceptions import (
    ApplicationException,
    NotFoundException,
)
from modernization_platform.db.models.budget import BudgetAccount, BudgetReservation
from modernization_platform.domain.model_gateway.errors import (
    ModelBudgetExceededError,
    ModelBudgetReservationError,
)

logger = logging.getLogger(__name__)


class BudgetRepository:
    """PostgreSQL repository handling budget persistence and transactional row-locked reservations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @log_errors
    def _translate_error(self, operation: str, exc: Exception) -> Exception:
        """Translate lower-level database errors into structured domain exceptions."""
        logger.exception("BudgetRepository.%s failed | %s: %s", operation, type(exc).__name__, exc)
        if isinstance(exc, ApplicationException):
            return exc
        return ApplicationException(
            message=f"Budget repository operation '{operation}' failed: {exc}",
            code="BUDGET_REPOSITORY_ERROR",
        )

    @log_errors
    async def create_or_get_account(
        self,
        *,
        job_id: uuid.UUID,
        scope_type: str = "job",
        scope_id: str = "job",
        limit_microcents: int = 500_000_000,  # default $500.00
        warning_threshold_percent: int = 80,
        hard_stop_percent: int = 100,
        currency: str = "USD",
    ) -> BudgetAccount:
        """Create a new budget account or retrieve the existing one for this job and scope."""
        try:
            stmt = select(BudgetAccount).where(
                BudgetAccount.job_id == job_id,
                BudgetAccount.scope_type == scope_type,
                BudgetAccount.scope_id == scope_id,
            )
            result = await self.session.execute(stmt)
            account = result.scalar_one_or_none()
            if account:
                return account

            account = BudgetAccount(
                id=uuid.uuid4(),
                job_id=job_id,
                scope_type=scope_type,
                scope_id=scope_id,
                limit_microcents=limit_microcents,
                reserved_microcents=0,
                spent_microcents=0,
                warning_threshold_percent=warning_threshold_percent,
                warning_emitted=False,
                hard_stop_percent=hard_stop_percent,
                currency=currency,
                status="active",
            )
            self.session.add(account)
            await self.session.flush()
            return account
        except Exception as exc:
            raise self._translate_error("create_or_get_account", exc) from exc

    @log_errors
    async def get_account_for_update(
        self,
        account_id: uuid.UUID,
    ) -> BudgetAccount | None:
        """Retrieve a budget account acquiring an exclusive row-level lock (FOR UPDATE)."""
        try:
            stmt = select(BudgetAccount).where(BudgetAccount.id == account_id).with_for_update()
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_account_for_update", exc) from exc

    @log_errors
    async def get_account_by_job_for_update(
        self,
        job_id: uuid.UUID,
        scope_type: str = "job",
        scope_id: str = "job",
    ) -> BudgetAccount | None:
        """Retrieve a job's budget account by scope acquiring an exclusive row-level lock."""
        try:
            stmt = (
                select(BudgetAccount)
                .where(
                    BudgetAccount.job_id == job_id,
                    BudgetAccount.scope_type == scope_type,
                    BudgetAccount.scope_id == scope_id,
                )
                .with_for_update()
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_account_by_job_for_update", exc) from exc

    @log_errors
    async def reserve_budget(
        self,
        *,
        job_id: uuid.UUID,
        agent_role: str,
        estimated_microcents: int,
        task_id: uuid.UUID | None = None,
        scope_type: str = "job",
        scope_id: str = "job",
        default_limit_microcents: int = 500_000_000,
        lease_duration_seconds: float = 300.0,
    ) -> tuple[BudgetReservation, bool]:
        """Atomically reserve funds under row-level lock; returns reservation and should_warn boolean."""
        try:
            # 1. Fetch account under row lock or create it
            account = await self.get_account_by_job_for_update(
                job_id, scope_type=scope_type, scope_id=scope_id
            )
            if not account:
                account = await self.create_or_get_account(
                    job_id=job_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    limit_microcents=default_limit_microcents,
                )
                # Re-lock created account
                account = await self.get_account_for_update(account.id)
                if not account:
                    raise ModelBudgetReservationError("Failed to lock created budget account")

            # 2. Check 100% hard stop threshold
            total_committed = account.spent_microcents + account.reserved_microcents
            projected_total = total_committed + estimated_microcents

            if projected_total > account.limit_microcents:
                from modernization_platform.domain.model_gateway.pricing import (
                    microcents_to_cents,
                )

                raise ModelBudgetExceededError(
                    scope=f"{scope_type}:{scope_id}",
                    limit_cents=microcents_to_cents(account.limit_microcents),
                    current_cents=microcents_to_cents(total_committed),
                    estimated_cents=microcents_to_cents(estimated_microcents),
                )

            # 3. Check 80% warning threshold
            warning_limit = (account.limit_microcents * account.warning_threshold_percent) // 100
            should_emit_warning = False
            if projected_total >= warning_limit and not account.warning_emitted:
                account.warning_emitted = True
                should_emit_warning = True

            # 4. Commit reservation increment
            account.reserved_microcents += estimated_microcents
            account.updated_at = datetime.now(UTC)

            reservation = BudgetReservation(
                id=uuid.uuid4(),
                budget_account_id=account.id,
                job_id=job_id,
                task_id=task_id,
                agent_role=agent_role,
                reserved_microcents=estimated_microcents,
                actual_microcents=None,
                status="reserved",
                expires_at=datetime.now(UTC) + timedelta(seconds=lease_duration_seconds),
                created_at=datetime.now(UTC),
            )
            self.session.add(reservation)
            await self.session.flush()

            return reservation, should_emit_warning
        except (ModelBudgetExceededError, ModelBudgetReservationError):
            raise
        except Exception as exc:
            raise self._translate_error("reserve_budget", exc) from exc

    @log_errors
    async def reconcile_reservation(
        self,
        *,
        reservation_id: uuid.UUID,
        actual_microcents: int,
    ) -> BudgetReservation:
        """Reconcile in-flight reservation with actual spend under row-level lock."""
        try:
            res_stmt = (
                select(BudgetReservation)
                .where(BudgetReservation.id == reservation_id)
                .with_for_update()
            )
            res_result = await self.session.execute(res_stmt)
            reservation = res_result.scalar_one_or_none()
            if not reservation:
                raise NotFoundException(f"Budget reservation '{reservation_id}' not found")

            if reservation.status != "reserved":
                logger.warning(
                    "Reservation %s already resolved with status %s",
                    reservation_id,
                    reservation.status,
                )
                return reservation

            account = await self.get_account_for_update(reservation.budget_account_id)
            if not account:
                raise NotFoundException(
                    f"Budget account '{reservation.budget_account_id}' not found"
                )

            # Release reserved amount, apply actual amount
            account.reserved_microcents = max(
                0, account.reserved_microcents - reservation.reserved_microcents
            )
            account.spent_microcents += max(0, actual_microcents)
            account.updated_at = datetime.now(UTC)

            if account.spent_microcents >= account.limit_microcents:
                account.status = "exhausted"

            reservation.actual_microcents = actual_microcents
            reservation.status = "reconciled"
            reservation.reconciled_at = datetime.now(UTC)

            await self.session.flush()
            return reservation
        except (NotFoundException, Exception) as exc:
            if isinstance(exc, NotFoundException):
                raise
            raise self._translate_error("reconcile_reservation", exc) from exc

    @log_errors
    async def release_reservation(
        self,
        reservation_id: uuid.UUID,
        reason: str = "cancelled",
    ) -> BudgetReservation:
        """Release a reserved amount without applying actual spend (e.g. on call error or abort)."""
        try:
            res_stmt = (
                select(BudgetReservation)
                .where(BudgetReservation.id == reservation_id)
                .with_for_update()
            )
            res_result = await self.session.execute(res_stmt)
            reservation = res_result.scalar_one_or_none()
            if not reservation or reservation.status != "reserved":
                return reservation or BudgetReservation(
                    id=reservation_id,
                    budget_account_id=uuid.uuid4(),
                    job_id=uuid.uuid4(),
                    agent_role="unknown",
                    reserved_microcents=0,
                    expires_at=datetime.now(UTC),
                )

            account = await self.get_account_for_update(reservation.budget_account_id)
            if account:
                account.reserved_microcents = max(
                    0, account.reserved_microcents - reservation.reserved_microcents
                )
                account.updated_at = datetime.now(UTC)

            reservation.status = "released"
            reservation.reconciled_at = datetime.now(UTC)
            await self.session.flush()
            return reservation
        except Exception as exc:
            raise self._translate_error("release_reservation", exc) from exc

    @log_errors
    async def list_job_budget_accounts(
        self,
        job_id: uuid.UUID,
    ) -> list[BudgetAccount]:
        """List all budget accounts associated with a job."""
        try:
            stmt = (
                select(BudgetAccount)
                .where(BudgetAccount.job_id == job_id)
                .order_by(BudgetAccount.scope_type)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_job_budget_accounts", exc) from exc


__all__ = ["BudgetRepository"]
