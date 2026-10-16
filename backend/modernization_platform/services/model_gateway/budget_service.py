"""Service layer for durable budget coordination, 80% warning alerts, and 100% hard stop enforcement."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.budget import BudgetAccount, BudgetReservation
from modernization_platform.domain.model_gateway.errors import (
    ModelBudgetExceededError,
)
from modernization_platform.observability.metrics import default_metrics_registry
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.budgets import BudgetRepository

logger = logging.getLogger(__name__)


class BudgetService:
    """Manages transactional budget reservation, warnings, reconciliation, and audit logs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.budget_repo = BudgetRepository(session)
        self.audit_repo = AuditEventRepository(session)

    @log_errors
    async def get_or_create_account(
        self,
        job_id: uuid.UUID,
        scope_type: str = "job",
        scope_id: str = "job",
        limit_microcents: int = 500_000_000,
        warning_threshold_percent: int = 80,
        hard_stop_percent: int = 100,
    ) -> BudgetAccount:
        """Fetch or initialize a budget account for the specified scope."""
        return await self.budget_repo.create_or_get_account(
            job_id=job_id,
            scope_type=scope_type,
            scope_id=scope_id,
            limit_microcents=limit_microcents,
            warning_threshold_percent=warning_threshold_percent,
            hard_stop_percent=hard_stop_percent,
        )

    @log_errors
    async def list_job_accounts(self, job_id: uuid.UUID) -> list[BudgetAccount]:
        """List all budget accounts belonging to a modernization job."""
        return await self.budget_repo.list_job_budget_accounts(job_id)

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
    ) -> BudgetReservation:
        """Atomically reserve funds under row-level lock.

        Emits an idempotent 80% warning audit event if the warning threshold is crossed,
        and enforces the 100% hard stop by raising ModelBudgetExceededError.
        """
        try:
            reservation, should_warn = await self.budget_repo.reserve_budget(
                job_id=job_id,
                agent_role=agent_role,
                estimated_microcents=estimated_microcents,
                task_id=task_id,
                scope_type=scope_type,
                scope_id=scope_id,
                default_limit_microcents=default_limit_microcents,
            )

            if should_warn:
                logger.warning(
                    "Job %s reached 80%% budget threshold under scope %s:%s",
                    job_id,
                    scope_type,
                    scope_id,
                )
                await self.audit_repo.append_event(
                    job_id=job_id,
                    action="BUDGET_WARNING_80_PERCENT",
                    actor=f"agent:{agent_role}",
                    payload={
                        "job_id": str(job_id),
                        "scope_type": scope_type,
                        "scope_id": scope_id,
                        "threshold_percent": 80,
                        "estimated_microcents": estimated_microcents,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )

            return reservation
        except ModelBudgetExceededError as exc:
            default_metrics_registry.record_budget_rejection("hard_stop")
            default_metrics_registry.record_budget_pause()
            logger.error("Job %s exceeded 100%% hard budget limit: %s", job_id, exc)
            await self.audit_repo.append_event(
                job_id=job_id,
                action="BUDGET_EXHAUSTED",
                actor=f"agent:{agent_role}",
                payload={
                    "job_id": str(job_id),
                    "scope": exc.scope,
                    "limit_cents": exc.limit_cents,
                    "current_cents": exc.current_cents,
                    "estimated_cents": exc.estimated_cents,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            raise
        except Exception as exc:
            logger.exception(
                "BudgetService.reserve_budget failed | %s: %s", type(exc).__name__, exc
            )
            raise

    @log_errors
    async def reconcile_reservation(
        self,
        *,
        reservation_id: uuid.UUID,
        actual_microcents: int,
    ) -> BudgetReservation:
        """Reconcile reservation against actual token expenditure."""
        return await self.budget_repo.reconcile_reservation(
            reservation_id=reservation_id,
            actual_microcents=actual_microcents,
        )

    @log_errors
    async def release_reservation(
        self,
        reservation_id: uuid.UUID,
        reason: str = "cancelled",
    ) -> BudgetReservation:
        """Release an uncommitted or aborted budget reservation."""
        return await self.budget_repo.release_reservation(reservation_id, reason=reason)


__all__ = ["BudgetService"]
