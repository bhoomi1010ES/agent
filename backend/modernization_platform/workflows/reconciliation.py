"""Reconciliation service synchronizing LangGraph workflow execution with PostgreSQL Job state."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.workflows.state import ModernizationWorkflowState

logger = logging.getLogger(__name__)


class WorkflowReconciliationService:
    """Service synchronizing LangGraph checkpoints and in-flight state with authoritative PostgreSQL jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._jobs = JobRepository(session)
        self._audit = AuditEventRepository(session)

    @log_errors
    async def reconcile_job_state(
        self,
        *,
        state: ModernizationWorkflowState,
        correlation_id: str | None = None,
        actor: str = "workflow_engine",
    ) -> Job | None:
        """Synchronize the current workflow state to the PostgreSQL Job table."""
        try:
            job_id_str = state.get("job_id")
            if not job_id_str:
                logger.warning("Reconciliation requested for workflow state lacking job_id")
                return None

            job_id = uuid.UUID(job_id_str)
            job = await self._jobs.get_by_id_unscoped(job_id)
            if job is None:
                logger.warning("Reconciliation skipped: Job %s not found in PostgreSQL", job_id)
                return None

            wf_status = state.get("status", JobLifecycleState.RUNNING.value)
            current_step = state.get("current_step", job.current_stage)
            needs_human = state.get("needs_human", False)

            # Map gate interrupt to AWAITING_APPROVAL in DB
            target_status = JobLifecycleState.AWAITING_APPROVAL.value if needs_human else wf_status

            now = datetime.now(UTC)
            started_at = job.started_at or (
                now if target_status == JobLifecycleState.RUNNING.value else None
            )
            paused_at = now if target_status == JobLifecycleState.PAUSED.value else None
            completed_at = now if target_status == JobLifecycleState.COMPLETED.value else None
            failed_at = now if target_status == JobLifecycleState.FAILED.value else None

            # Only perform update if status or stage changed
            if job.status != target_status or job.current_stage != current_step:
                prev_status = job.status
                resolved_tenant_id = job.tenant_id or uuid.UUID(
                    str(state.get("tenant_id", "00000000-0000-0000-0000-000000000000"))
                )
                updated_job = await self._jobs.update_lifecycle_state(
                    job_id=job.id,
                    tenant_id=resolved_tenant_id,
                    user_id=job.owner_user_id or uuid.UUID(int=0),
                    membership_id=uuid.UUID(int=0),
                    tenant_admin=True,
                    expected_version=job.version,
                    new_status=target_status,
                    current_stage=current_step,
                    started_at=started_at,
                    paused_at=paused_at,
                    completed_at=completed_at,
                    failed_at=failed_at,
                    failure_reason=state.get("failure_reason"),
                    failure_classification=state.get("failure_classification"),
                )

                await self._audit.append_event(
                    actor=actor,
                    actor_user_id=job.owner_user_id,
                    action=f"WORKFLOW_STATE_{target_status.upper()}",
                    job_id=job.id,
                    correlation_id=correlation_id,
                    payload={
                        "previous_status": prev_status,
                        "new_status": target_status,
                        "current_stage": current_step,
                        "iteration_count": state.get("iteration_count", 0),
                        "completed_steps": state.get("completed_steps", []),
                    },
                )
                logger.info(
                    "Reconciled job %s from %s to %s (stage=%s)",
                    job.id,
                    prev_status,
                    target_status,
                    current_step,
                )
                return updated_job

            return job
        except Exception as exc:
            logger.exception(
                "WorkflowReconciliationService.reconcile_job_state failed | %s: %s",
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def record_gate_opened(
        self,
        *,
        job_id: uuid.UUID,
        gate_type: str,
        artifact_references: dict[str, Any],
        actor: str = "workflow_engine",
        correlation_id: str | None = None,
    ) -> None:
        """Record an audit event when a workflow halts at an approval gate."""
        try:
            await self._audit.append_event(
                actor=actor,
                action="WORKFLOW_GATE_ENTERED",
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "gate_type": gate_type,
                    "artifact_references": artifact_references,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            logger.exception(
                "WorkflowReconciliationService.record_gate_opened failed | %s: %s",
                type(exc).__name__,
                exc,
            )
            raise


__all__ = ["WorkflowReconciliationService"]
