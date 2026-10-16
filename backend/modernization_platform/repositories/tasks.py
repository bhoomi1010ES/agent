"""Task persistence repository implementing atomic transactional claiming, lease renewal, and completion."""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.job import Job
from modernization_platform.db.models.task import Task
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.tasks.errors import (
    DuplicateFinalizationError,
    LeaseLostError,
)
from modernization_platform.domain.tasks.states import (
    TaskFailureClassification,
    TaskLifecycleState,
)
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class TaskRepository(BaseRepository[Task]):
    """Repository handling atomic task claiming, conditional lease management, and completion."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.audit_events = AuditEventRepository(session)

    @log_errors
    async def create_task(
        self,
        *,
        job_id: uuid.UUID,
        task_type: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
        workflow_thread_id: str | None = None,
        task_id: uuid.UUID | None = None,
    ) -> Task:
        """Persist a new pending task bound to a job."""
        try:
            task = Task(
                id=task_id or uuid.uuid4(),
                job_id=job_id,
                task_type=task_type,
                status=TaskLifecycleState.PENDING.value,
                max_attempts=max_attempts,
                payload=payload or {},
                workflow_thread_id=workflow_thread_id,
                attempt_count=0,
            )
            self.session.add(task)
            await self.session.flush()
            logger.info("Created task %s of type '%s' for job %s", task.id, task_type, job_id)
            return task
        except Exception as exc:
            logger.exception("TaskRepository.create_task failed | %s: %s", type(exc).__name__, exc)
            raise self._translate_error("create_task", exc) from exc

    @log_errors
    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        """Lookup a task by primary key."""
        try:
            stmt = select(Task).where(Task.id == task_id)
            result = await self.session.execute(stmt)
            return result.scalars().first()
        except Exception as exc:
            logger.exception(
                "TaskRepository.get_by_id failed for %s | %s: %s", task_id, type(exc).__name__, exc
            )
            raise self._translate_error("get_by_id", exc) from exc

    @log_errors
    async def claim_next_task(
        self,
        *,
        worker_id: str,
        lease_seconds: float = 30.0,
        task_types: Sequence[str] | None = None,
    ) -> Task | None:
        """Atomically claim the next eligible pending, retryable, or expired task using SELECT FOR UPDATE SKIP LOCKED."""
        try:
            now = datetime.now(UTC)
            lease_duration = timedelta(seconds=lease_seconds)

            # A task is claimable if:
            # 1. status is 'pending'
            # 2. status is 'retry_wait' AND retry_at <= now
            # 3. status is 'running' AND lease_expires_at < now (expired lease crash recovery)
            claimable_status = or_(
                Task.status == TaskLifecycleState.PENDING.value,
                and_(
                    Task.status == TaskLifecycleState.RETRY_WAIT.value,
                    or_(Task.retry_at.is_(None), Task.retry_at <= now),
                ),
                and_(
                    Task.status == TaskLifecycleState.RUNNING.value,
                    Task.lease_expires_at < now,
                ),
            )

            # Job must not be cancelled
            stmt = (
                select(Task)
                .join(Job, Task.job_id == Job.id)
                .where(
                    claimable_status,
                    Job.status != JobLifecycleState.CANCELLED.value,
                )
            )

            if task_types:
                stmt = stmt.where(Task.task_type.in_(task_types))

            # Prioritize expired running tasks (recovery), then retry_wait, then pending by creation time
            stmt = (
                stmt.order_by(
                    # Ordering: running (expired recovery first) -> retry_wait -> pending
                    Task.status.desc(),
                    Task.created_at.asc(),
                    Task.id.asc(),
                )
                .limit(1)
                .with_for_update(of=Task, skip_locked=True)
            )

            result = await self.session.execute(stmt)
            task = result.scalars().first()

            if task is None:
                return None

            # Atomically update task with lease ownership
            task.worker_id = worker_id
            task.status = TaskLifecycleState.RUNNING.value
            task.attempt_count += 1
            task.lease_expires_at = now + lease_duration
            task.started_at = task.started_at or now
            task.updated_at = now

            await self.session.flush()
            audit_action = "TASK_RECLAIMED" if task.attempt_count > 1 else "TASK_CLAIMED"
            await self.audit_events.append_event(
                actor=worker_id,
                action=audit_action,
                job_id=task.job_id,
                payload={
                    "task_id": str(task.id),
                    "task_type": task.task_type,
                    "attempt_count": task.attempt_count,
                    "lease_expires_at": task.lease_expires_at.isoformat()
                    if task.lease_expires_at
                    else None,
                },
            )
            logger.info(
                "Worker '%s' claimed task %s (attempt %d, expires %s)",
                worker_id,
                task.id,
                task.attempt_count,
                task.lease_expires_at.isoformat(),
            )
            return task
        except Exception as exc:
            logger.exception(
                "TaskRepository.claim_next_task failed for worker '%s' | %s: %s",
                worker_id,
                type(exc).__name__,
                exc,
            )
            raise self._translate_error("claim_next_task", exc) from exc

    @log_errors
    async def renew_lease(
        self,
        *,
        task_id: uuid.UUID,
        worker_id: str,
        extend_seconds: float = 30.0,
    ) -> bool:
        """Extend the lease expiration for an active task if and only if the caller currently owns the valid lease."""
        try:
            now = datetime.now(UTC)
            new_expiry = now + timedelta(seconds=extend_seconds)

            stmt = (
                update(Task)
                .where(
                    Task.id == task_id,
                    Task.worker_id == worker_id,
                    Task.status == TaskLifecycleState.RUNNING.value,
                    Task.lease_expires_at >= now,
                )
                .values(
                    lease_expires_at=new_expiry,
                    updated_at=now,
                )
                .returning(Task.id)
            )

            result = await self.session.execute(stmt)
            updated_id = result.scalar_one_or_none()
            if updated_id is not None:
                logger.debug(
                    "Renewed lease for task %s by worker '%s' until %s",
                    task_id,
                    worker_id,
                    new_expiry,
                )
                return True

            logger.warning(
                "Failed to renew lease for task %s by worker '%s' (lease lost or task inactive)",
                task_id,
                worker_id,
            )
            return False
        except Exception as exc:
            logger.exception(
                "TaskRepository.renew_lease failed for task %s | %s: %s",
                task_id,
                type(exc).__name__,
                exc,
            )
            raise self._translate_error("renew_lease", exc) from exc

    @log_errors
    async def complete_task(
        self,
        *,
        task_id: uuid.UUID,
        worker_id: str,
        result_payload: dict[str, Any] | None = None,
    ) -> None:
        """Mark a task successfully completed conditional on valid lease ownership.

        Raises:
            LeaseLostError: If the worker has lost ownership or the lease has expired.
            DuplicateFinalizationError: If the task is already finalized.
        """
        try:
            now = datetime.now(UTC)

            # Check if task was already finalized
            task = await self.get_by_id(task_id)
            if task is None:
                raise LeaseLostError(f"Task {task_id} not found")
            if task.status == TaskLifecycleState.COMPLETED.value:
                raise DuplicateFinalizationError(
                    f"Task {task_id} has already been completed; rejecting duplicate completion from worker '{worker_id}'"
                )

            stmt = (
                update(Task)
                .where(
                    Task.id == task_id,
                    Task.worker_id == worker_id,
                    Task.status == TaskLifecycleState.RUNNING.value,
                    Task.lease_expires_at >= now,
                )
                .values(
                    status=TaskLifecycleState.COMPLETED.value,
                    result=result_payload or {},
                    completed_at=now,
                    lease_expires_at=None,
                    updated_at=now,
                )
                .returning(Task.id)
            )

            res = await self.session.execute(stmt)
            updated_id = res.scalar_one_or_none()
            if updated_id is None:
                raise LeaseLostError(
                    f"Worker '{worker_id}' lost lease on task {task_id}; completion rejected"
                )

            await self.audit_events.append_event(
                actor=worker_id,
                action="TASK_COMPLETED",
                job_id=task.job_id,
                payload={"task_id": str(task_id), "completed_at": now.isoformat()},
            )
            logger.info("Worker '%s' completed task %s successfully", worker_id, task_id)
        except (LeaseLostError, DuplicateFinalizationError):
            raise
        except Exception as exc:
            logger.exception(
                "TaskRepository.complete_task failed for task %s | %s: %s",
                task_id,
                type(exc).__name__,
                exc,
            )
            raise self._translate_error("complete_task", exc) from exc

    @log_errors
    async def fail_task(
        self,
        *,
        task_id: uuid.UUID,
        worker_id: str,
        error_message: str,
        classification: TaskFailureClassification,
        retry_backoff_seconds: float = 5.0,
    ) -> None:
        """Record task failure and schedule retry or mark terminal failure based on classification and attempt count."""
        try:
            now = datetime.now(UTC)
            task = await self.get_by_id(task_id)
            if task is None:
                raise LeaseLostError(f"Task {task_id} not found")

            # Check if eligible for retry
            can_retry = (
                classification == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
                and task.attempt_count < task.max_attempts
            )

            if can_retry:
                next_status = TaskLifecycleState.RETRY_WAIT.value
                retry_at = now + timedelta(seconds=retry_backoff_seconds)
                completed_at = None
                worker_to_set = None
                logger.info(
                    "Scheduling retry for task %s (attempt %d/%d) at %s",
                    task_id,
                    task.attempt_count,
                    task.max_attempts,
                    retry_at.isoformat(),
                )
            else:
                next_status = TaskLifecycleState.FAILED.value
                retry_at = None
                completed_at = now
                worker_to_set = worker_id
                logger.warning(
                    "Task %s permanently failed after %d attempts: %s",
                    task_id,
                    task.attempt_count,
                    error_message,
                )

            stmt = (
                update(Task)
                .where(
                    Task.id == task_id,
                    Task.worker_id == worker_id,
                    Task.status == TaskLifecycleState.RUNNING.value,
                )
                .values(
                    status=next_status,
                    last_error=error_message,
                    failure_classification=classification.value,
                    retry_at=retry_at,
                    completed_at=completed_at,
                    lease_expires_at=None,
                    worker_id=worker_to_set,
                    updated_at=now,
                )
                .returning(Task.id)
            )

            res = await self.session.execute(stmt)
            if res.scalar_one_or_none() is None:
                raise LeaseLostError(
                    f"Worker '{worker_id}' lost ownership of task {task_id} while recording failure"
                )

            audit_action = "TASK_RETRY_SCHEDULED" if can_retry else "TASK_FAILED"
            await self.audit_events.append_event(
                actor=worker_id,
                action=audit_action,
                job_id=task.job_id,
                payload={
                    "task_id": str(task_id),
                    "attempt_count": task.attempt_count,
                    "classification": classification.value,
                    "error": error_message,
                },
            )
        except LeaseLostError:
            raise
        except Exception as exc:
            logger.exception(
                "TaskRepository.fail_task failed for task %s | %s: %s",
                task_id,
                type(exc).__name__,
                exc,
            )
            raise self._translate_error("fail_task", exc) from exc

    @log_errors
    async def cancel_task(
        self,
        *,
        task_id: uuid.UUID,
        reason: str,
        worker_id: str | None = None,
    ) -> bool:
        """Cancel an in-flight or pending task."""
        try:
            now = datetime.now(UTC)
            conditions = [
                Task.id == task_id,
                Task.status.in_(
                    [
                        TaskLifecycleState.PENDING.value,
                        TaskLifecycleState.RUNNING.value,
                        TaskLifecycleState.RETRY_WAIT.value,
                    ]
                ),
            ]
            if worker_id is not None:
                conditions.append(Task.worker_id == worker_id)

            stmt = (
                update(Task)
                .where(and_(*conditions))
                .values(
                    status=TaskLifecycleState.CANCELLED.value,
                    cancellation_reason=reason,
                    completed_at=now,
                    lease_expires_at=None,
                    updated_at=now,
                )
                .returning(Task.id)
            )

            res = await self.session.execute(stmt)
            cancelled = res.scalar_one_or_none() is not None
            if cancelled:
                task = await self.get_by_id(task_id)
                if task is not None:
                    await self.audit_events.append_event(
                        actor=worker_id or "system",
                        action="TASK_CANCELLED",
                        job_id=task.job_id,
                        payload={"task_id": str(task_id), "reason": reason},
                    )
            return cancelled
        except Exception as exc:
            logger.exception(
                "TaskRepository.cancel_task failed for %s | %s: %s",
                task_id,
                type(exc).__name__,
                exc,
            )
            raise self._translate_error("cancel_task", exc) from exc

    @log_errors
    async def release_lease(
        self,
        *,
        task_id: uuid.UUID,
        worker_id: str,
    ) -> bool:
        """Safely release an active lease back to pending status for graceful worker shutdown."""
        try:
            now = datetime.now(UTC)
            stmt = (
                update(Task)
                .where(
                    Task.id == task_id,
                    Task.worker_id == worker_id,
                    Task.status == TaskLifecycleState.RUNNING.value,
                )
                .values(
                    status=TaskLifecycleState.PENDING.value,
                    worker_id=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
                .returning(Task.id)
            )

            res = await self.session.execute(stmt)
            released = res.scalar_one_or_none() is not None
            if released:
                logger.info("Worker '%s' released lease on task %s", worker_id, task_id)
            return released
        except Exception as exc:
            logger.exception(
                "TaskRepository.release_lease failed for %s | %s: %s",
                task_id,
                type(exc).__name__,
                exc,
            )
            raise self._translate_error("release_lease", exc) from exc

    @log_errors
    async def list_tasks_for_job(self, job_id: uuid.UUID) -> list[Task]:
        """Retrieve all tasks for a specific modernization job."""
        try:
            stmt = select(Task).where(Task.job_id == job_id).order_by(Task.created_at.asc())
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            logger.exception(
                "TaskRepository.list_tasks_for_job failed for %s | %s: %s",
                job_id,
                type(exc).__name__,
                exc,
            )
            raise self._translate_error("list_tasks_for_job", exc) from exc

    @log_errors
    async def count_active_tasks_for_worker(self, worker_id: str) -> int:
        """Count currently running tasks leased to a specific worker."""
        try:
            now = datetime.now(UTC)
            stmt = select(Task).where(
                Task.worker_id == worker_id,
                Task.status == TaskLifecycleState.RUNNING.value,
                Task.lease_expires_at >= now,
            )
            result = await self.session.execute(stmt)
            return len(list(result.scalars().all()))
        except Exception as exc:
            logger.exception(
                "count_active_tasks_for_worker failed for %s | %s: %s",
                worker_id,
                type(exc).__name__,
                exc,
            )
            raise self._translate_error("count_active_tasks_for_worker", exc) from exc


__all__ = ["TaskRepository"]
