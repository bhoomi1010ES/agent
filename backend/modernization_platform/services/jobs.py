"""Job lifecycle service managing job creation, inspection, and state machine transitions."""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.config import get_settings
from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.identity import JobMember
from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.errors import (
    IdempotencyConflictError,
    JobNotFoundError,
    UnauthorizedJobActionError,
)
from modernization_platform.domain.jobs.states import (
    FailureClassification,
    JobLifecycleState,
)
from modernization_platform.domain.jobs.transitions import (
    CompletionCheckResult,
    CompletionGuard,
    normalize_state,
    validate_transition,
)
from modernization_platform.integrations.git.policy import GitSecurityPolicy
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.gates import GateRepository
from modernization_platform.repositories.idempotency import (
    IdempotencyRepository,
    compute_request_hash,
)
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.schemas.jobs import (
    JobDetailResponse,
    JobStatusResponse,
    JobSummaryResponse,
)
from modernization_platform.schemas.status import JobStatus
from modernization_platform.security.authorization import (
    has_tenant_admin_scope,
    require_permission,
)
from modernization_platform.security.permissions import Permission
from modernization_platform.security.principals import AuthenticatedPrincipal

logger = logging.getLogger(__name__)


class JobService:
    """Service layer owning job lifecycle state transitions and concurrency."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._jobs = JobRepository(session)
        self._audit = AuditEventRepository(session)
        self._idempotency = IdempotencyRepository(session)
        self._gates = GateRepository(session)

    @log_errors
    async def create_job(
        self,
        *,
        principal: AuthenticatedPrincipal,
        source_repository: str,
        source_revision: str,
        target_stack_spec: dict[str, Any],
        budget: dict[str, Any],
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Job:
        """Create a modernization job transactionally with idempotency protection and audit logging."""
        try:
            require_permission(principal, Permission.JOB_CREATE)

            # Validate source repository URL according to Git security policy
            settings = get_settings()
            policy = GitSecurityPolicy(
                allowed_hosts=settings.git_allowed_hosts,
                allow_private_ips_for_testing=settings.git_allow_private_ips_for_testing,
            )
            validated_repo_url = policy.validate_url(source_repository)

            # Idempotency check if key supplied
            if idempotency_key:
                payload = {
                    "source_repository": source_repository,
                    "source_revision": source_revision,
                    "target_stack": target_stack_spec,
                    "budget": budget,
                }
                req_hash = compute_request_hash(payload)
                existing = await self._idempotency.get_record(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    action="create_job",
                    key=idempotency_key,
                )
                if existing is not None:
                    if existing.request_hash != req_hash:
                        logger.warning(
                            "Idempotency conflict on create_job | key=%s tenant_id=%s user_id=%s",
                            idempotency_key,
                            principal.tenant_id,
                            principal.user_id,
                        )
                        raise IdempotencyConflictError(idempotency_key)
                    # Return existing persisted job
                    if existing.resource_id:
                        job = await self._jobs.get_by_id_scoped(
                            job_id=existing.resource_id,
                            tenant_id=principal.tenant_id,
                            user_id=principal.user_id,
                            membership_id=principal.membership_id,
                            tenant_admin=has_tenant_admin_scope(principal),
                        )
                        if job is not None:
                            return job

            source_ref = f"{validated_repo_url}@{source_revision}"
            job = await self._jobs.create_job(
                owner=str(principal.user_id),
                source_ref=source_ref,
                source_revision=source_revision,
                target_stack_spec=target_stack_spec,
                budget=budget,
                tenant_id=principal.tenant_id,
                owner_user_id=principal.user_id,
                status=JobLifecycleState.QUEUED.value,
                current_stage="queued",
            )
            job_member = JobMember(job_id=job.id, membership_id=principal.membership_id)
            self._session.add(job_member)
            await self._session.flush()

            # Audit event
            await self._audit.append_event(
                actor=str(principal.user_id),
                actor_user_id=principal.user_id,
                action="JOB_CREATED",
                job_id=job.id,
                correlation_id=correlation_id,
                payload={
                    "source_repository": source_repository,
                    "source_revision": source_revision,
                    "target_stack": target_stack_spec,
                    "budget": budget,
                    "initial_state": JobLifecycleState.QUEUED.value,
                    "version": job.version,
                },
            )

            # Persist idempotency record if requested
            if idempotency_key:
                await self._idempotency.save_record(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    action="create_job",
                    key=idempotency_key,
                    request_hash=req_hash,
                    response_code=201,
                    response_body={
                        "job_id": str(job.id),
                        "status": job.status,
                        "created_at": job.created_at.isoformat() if job.created_at else None,
                        "version": job.version,
                    },
                    resource_id=job.id,
                )

            return job
        except (IdempotencyConflictError, UnauthorizedJobActionError):
            raise
        except Exception as exc:
            logger.exception("JobService.create_job failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def get_job(
        self,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
    ) -> Job:
        """Retrieve a job within authorized scope."""
        try:
            require_permission(principal, Permission.JOB_VIEW)
            job = await self._jobs.get_by_id_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
            )
            if job is None:
                raise JobNotFoundError(str(job_id))
            return job
        except JobNotFoundError:
            raise
        except Exception as exc:
            logger.exception("JobService.get_job failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def list_jobs(
        self,
        *,
        principal: AuthenticatedPrincipal,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Job], int]:
        """List jobs visible to principal within authorized scope."""
        try:
            require_permission(principal, Permission.JOB_VIEW)
            jobs = await self._jobs.list_jobs_scoped(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                limit=limit,
                offset=offset,
                status=status,
            )
            total = await self._jobs.count_jobs_scoped(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                status=status,
            )
            return jobs, total
        except Exception as exc:
            logger.exception("JobService.list_jobs failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def get_job_status(
        self,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
    ) -> JobStatusResponse:
        """Inspect and return current job lifecycle status and stage."""
        try:
            job = await self.get_job(principal, job_id)
            status_enum = JobStatus(job.status)
            needs_human = status_enum == JobStatus.AWAITING_APPROVAL

            return JobStatusResponse(
                job_id=job.id,
                status=status_enum,
                current_stage=job.current_stage,
                version=job.version,
                needs_human=needs_human,
                status_message=job.failure_reason if status_enum == JobStatus.FAILED else None,
                failure_classification=job.failure_classification,
                failure_reason=job.failure_reason,
                created_at=job.created_at,
                updated_at=job.updated_at or job.created_at or datetime.now(UTC),
                started_at=job.started_at,
                paused_at=job.paused_at,
                completed_at=job.completed_at,
                cancelled_at=job.cancelled_at,
                failed_at=job.failed_at,
            )
        except Exception as exc:
            logger.exception("JobService.get_job_status failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def pause_job(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        expected_version: int,
        reason: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Job:
        """Cooperatively pause a running modernization job."""
        try:
            require_permission(principal, Permission.JOB_MANAGE)

            if idempotency_key:
                payload = {
                    "action": "pause",
                    "job_id": str(job_id),
                    "expected_version": expected_version,
                    "reason": reason,
                }
                req_hash = compute_request_hash(payload)
                existing = await self._idempotency.get_record(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    action="pause_job",
                    key=idempotency_key,
                )
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise IdempotencyConflictError(idempotency_key)
                    return await self.get_job(principal, job_id)

            tenant_admin = has_tenant_admin_scope(principal)
            job = await self._jobs.get_by_id_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=tenant_admin,
                for_update=True,
            )
            if job is None:
                raise JobNotFoundError(str(job_id))

            # Validate transition
            validate_transition(job.status, JobLifecycleState.PAUSED)

            now = datetime.now(UTC)
            prev_state = job.status
            updated_job = await self._jobs.update_lifecycle_state(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=tenant_admin,
                expected_version=expected_version,
                new_status=JobLifecycleState.PAUSED.value,
                paused_at=now,
            )

            await self._audit.append_event(
                actor=str(principal.user_id),
                actor_user_id=principal.user_id,
                action="JOB_PAUSED",
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "previous_state": prev_state,
                    "new_state": JobLifecycleState.PAUSED.value,
                    "expected_version": expected_version,
                    "resulting_version": updated_job.version,
                    "reason": reason,
                    "timestamp": now.isoformat(),
                },
            )

            if idempotency_key:
                await self._idempotency.save_record(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    action="pause_job",
                    key=idempotency_key,
                    request_hash=req_hash,
                    response_code=200,
                    response_body={
                        "job_id": str(job_id),
                        "status": updated_job.status,
                        "version": updated_job.version,
                        "action": "pause",
                    },
                    resource_id=job_id,
                )

            return updated_job
        except Exception as exc:
            logger.exception("JobService.pause_job failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def resume_job(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        expected_version: int,
        reason: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Job:
        """Resume a paused modernization job."""
        try:
            require_permission(principal, Permission.JOB_MANAGE)

            if idempotency_key:
                payload = {
                    "action": "resume",
                    "job_id": str(job_id),
                    "expected_version": expected_version,
                    "reason": reason,
                }
                req_hash = compute_request_hash(payload)
                existing = await self._idempotency.get_record(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    action="resume_job",
                    key=idempotency_key,
                )
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise IdempotencyConflictError(idempotency_key)
                    return await self.get_job(principal, job_id)

            tenant_admin = has_tenant_admin_scope(principal)
            job = await self._jobs.get_by_id_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=tenant_admin,
                for_update=True,
            )
            if job is None:
                raise JobNotFoundError(str(job_id))

            # Validate transition
            validate_transition(job.status, JobLifecycleState.RUNNING)

            now = datetime.now(UTC)
            prev_state = job.status
            started_at = job.started_at or now

            updated_job = await self._jobs.update_lifecycle_state(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=tenant_admin,
                expected_version=expected_version,
                new_status=JobLifecycleState.RUNNING.value,
                started_at=started_at,
            )

            await self._audit.append_event(
                actor=str(principal.user_id),
                actor_user_id=principal.user_id,
                action="JOB_RESUMED",
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "previous_state": prev_state,
                    "new_state": JobLifecycleState.RUNNING.value,
                    "expected_version": expected_version,
                    "resulting_version": updated_job.version,
                    "reason": reason,
                    "timestamp": now.isoformat(),
                },
            )

            if idempotency_key:
                await self._idempotency.save_record(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    action="resume_job",
                    key=idempotency_key,
                    request_hash=req_hash,
                    response_code=200,
                    response_body={
                        "job_id": str(job_id),
                        "status": updated_job.status,
                        "version": updated_job.version,
                        "action": "resume",
                    },
                    resource_id=job_id,
                )

            return updated_job
        except Exception as exc:
            logger.exception("JobService.resume_job failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def cancel_job(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        expected_version: int,
        reason: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Job:
        """Cooperatively and durably cancel a modernization job."""
        try:
            require_permission(principal, Permission.JOB_CANCEL)

            if idempotency_key:
                payload = {
                    "action": "cancel",
                    "job_id": str(job_id),
                    "expected_version": expected_version,
                    "reason": reason,
                }
                req_hash = compute_request_hash(payload)
                existing = await self._idempotency.get_record(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    action="cancel_job",
                    key=idempotency_key,
                )
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise IdempotencyConflictError(idempotency_key)
                    return await self.get_job(principal, job_id)

            tenant_admin = has_tenant_admin_scope(principal)
            job = await self._jobs.get_by_id_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=tenant_admin,
                for_update=True,
            )
            if job is None:
                raise JobNotFoundError(str(job_id))

            # Validate transition
            validate_transition(job.status, JobLifecycleState.CANCELLED)

            now = datetime.now(UTC)
            prev_state = job.status

            updated_job = await self._jobs.update_lifecycle_state(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=tenant_admin,
                expected_version=expected_version,
                new_status=JobLifecycleState.CANCELLED.value,
                cancelled_at=now,
                finished_at=now,
            )

            await self._audit.append_event(
                actor=str(principal.user_id),
                actor_user_id=principal.user_id,
                action="JOB_CANCELLED",
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "previous_state": prev_state,
                    "new_state": JobLifecycleState.CANCELLED.value,
                    "expected_version": expected_version,
                    "resulting_version": updated_job.version,
                    "reason": reason,
                    "timestamp": now.isoformat(),
                },
            )

            if idempotency_key:
                await self._idempotency.save_record(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    action="cancel_job",
                    key=idempotency_key,
                    request_hash=req_hash,
                    response_code=200,
                    response_body={
                        "job_id": str(job_id),
                        "status": updated_job.status,
                        "version": updated_job.version,
                        "action": "cancel",
                    },
                    resource_id=job_id,
                )

            return updated_job
        except Exception as exc:
            logger.exception("JobService.cancel_job failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def transition_job(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        target_state: JobLifecycleState | str,
        expected_version: int,
        current_stage: str | None = None,
        failure_classification: FailureClassification | str | None = None,
        failure_reason: str | None = None,
        is_retry: bool = False,
        completed_stages: Sequence[str] | None = None,
        has_pending_gates: bool = False,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> Job:
        """Transition job lifecycle state with state machine rules and completion guard."""
        try:
            require_permission(principal, Permission.JOB_MANAGE)
            tenant_admin = has_tenant_admin_scope(principal)

            job = await self._jobs.get_by_id_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=tenant_admin,
                for_update=True,
            )
            if job is None:
                raise JobNotFoundError(str(job_id))

            target_enum = normalize_state(target_state)

            # Evaluate completion guard if target is COMPLETED
            guard_result = None
            if target_enum == JobLifecycleState.COMPLETED:
                guard_result = await self.can_complete_job(
                    principal=principal,
                    job_id=job_id,
                    current_stage=current_stage,
                    completed_stages=completed_stages,
                    has_pending_gates=has_pending_gates,
                )

            validate_transition(
                job.status,
                target_enum,
                failure_classification=failure_classification,
                is_retry=is_retry,
                guard_result=guard_result,
            )

            now = datetime.now(UTC)
            prev_state = job.status
            started_at = (
                now if target_enum == JobLifecycleState.RUNNING and not job.started_at else None
            )
            paused_at = now if target_enum == JobLifecycleState.PAUSED else None
            completed_at = now if target_enum == JobLifecycleState.COMPLETED else None
            cancelled_at = now if target_enum == JobLifecycleState.CANCELLED else None
            failed_at = now if target_enum == JobLifecycleState.FAILED else None
            finished_at = (
                now
                if target_enum
                in (
                    JobLifecycleState.COMPLETED,
                    JobLifecycleState.CANCELLED,
                    JobLifecycleState.FAILED,
                )
                else None
            )

            classification_str = (
                failure_classification.value
                if isinstance(failure_classification, FailureClassification)
                else failure_classification
            )

            updated_job = await self._jobs.update_lifecycle_state(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=tenant_admin,
                expected_version=expected_version,
                new_status=target_enum.value,
                current_stage=current_stage,
                started_at=started_at,
                paused_at=paused_at,
                completed_at=completed_at,
                cancelled_at=cancelled_at,
                failed_at=failed_at,
                finished_at=finished_at,
                failure_reason=failure_reason or reason,
                failure_classification=classification_str,
            )

            await self._audit.append_event(
                actor=str(principal.user_id),
                actor_user_id=principal.user_id,
                action="JOB_STATE_TRANSITION",
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "previous_state": prev_state,
                    "new_state": target_enum.value,
                    "expected_version": expected_version,
                    "resulting_version": updated_job.version,
                    "current_stage": current_stage,
                    "reason": reason,
                    "failure_classification": classification_str,
                    "failure_reason": failure_reason,
                    "timestamp": now.isoformat(),
                },
            )

            return updated_job
        except Exception as exc:
            logger.exception("JobService.transition_job failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def can_complete_job(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        current_stage: str | None = None,
        completed_stages: Sequence[str] | None = None,
        has_pending_gates: bool | None = None,
    ) -> CompletionCheckResult:
        """Check whether a job is eligible to complete according to the domain completion guard."""
        try:
            require_permission(principal, Permission.JOB_VIEW)
            job = await self.get_job(principal, job_id)

            # Check if any gates on this job remain pending if not explicitly specified
            if has_pending_gates is None:
                gates = await self._gates.list_gates_by_job_scoped(
                    job_id=job_id,
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    membership_id=principal.membership_id,
                    tenant_admin=has_tenant_admin_scope(principal),
                    state="pending",
                )
                pending_gates_present = len(gates) > 0
            else:
                pending_gates_present = has_pending_gates

            return CompletionGuard.can_complete(
                job=job,
                current_stage=current_stage,
                completed_stages=completed_stages,
                has_pending_gates=pending_gates_present,
            )
        except Exception as exc:
            logger.exception("JobService.can_complete_job failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    def to_detail_response(self, job: Job) -> JobDetailResponse:
        """Convert a Job ORM entity into a validated JobDetailResponse contract."""
        try:
            if job.tenant_id is None or job.owner_user_id is None:
                raise ValueError("Job record is missing required tenant or owner identity")
            version_val = getattr(job, "version", 1) or 1
            return JobDetailResponse(
                job_id=job.id,
                tenant_id=job.tenant_id,
                owner_user_id=job.owner_user_id,
                status=JobStatus(job.status),
                source_ref=job.source_ref,
                target_stack_spec=job.target_stack_spec,
                budget=job.budget,
                version=version_val,
                current_stage=job.current_stage,
                created_at=job.created_at or datetime.now(UTC),
                updated_at=job.updated_at or job.created_at or datetime.now(UTC),
                started_at=job.started_at,
                paused_at=job.paused_at,
                completed_at=job.completed_at,
                cancelled_at=job.cancelled_at,
                failed_at=job.failed_at,
                finished_at=job.finished_at,
                failure_reason=job.failure_reason,
                failure_classification=job.failure_classification,
            )
        except Exception as exc:
            logger.exception("to_detail_response failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    def to_summary_response(
        self,
        job: Job,
        default_tenant_id: uuid.UUID,
        default_user_id: uuid.UUID,
    ) -> JobSummaryResponse:
        """Convert a Job ORM entity into a validated JobSummaryResponse contract."""
        try:
            version_val = getattr(job, "version", 1) or 1
            return JobSummaryResponse(
                job_id=job.id,
                tenant_id=job.tenant_id or default_tenant_id,
                owner_user_id=job.owner_user_id or default_user_id,
                status=JobStatus(job.status),
                source_ref=job.source_ref,
                target_stack_spec=job.target_stack_spec,
                budget=job.budget,
                version=version_val,
                current_stage=job.current_stage,
                created_at=job.created_at or datetime.now(UTC),
                updated_at=job.updated_at or job.created_at or datetime.now(UTC),
                finished_at=job.finished_at,
            )
        except Exception as exc:
            logger.exception("to_summary_response failed | %s: %s", type(exc).__name__, exc)
            raise


__all__ = ["JobService"]
