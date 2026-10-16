"""Workflow execution worker with task leases, crash recovery, and durable checkpoint resumption."""

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.config.settings import get_settings
from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.task import Task
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.tasks.errors import LeaseLostError
from modernization_platform.domain.tasks.retry import TaskRetryPolicy, classify_exception
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.repositories.tasks import TaskRepository
from modernization_platform.workers.base import BaseWorker
from modernization_platform.workers.lease_manager import LeaseManager
from modernization_platform.workflows.engine import WorkflowEngine
from modernization_platform.workflows.state import ModernizationWorkflowState

logger = logging.getLogger(__name__)
settings = get_settings()


class WorkflowWorker(BaseWorker):
    """Background worker executing modernization workflows with durable leases and checkpoint recovery."""

    def __init__(
        self,
        engine: WorkflowEngine,
        session_factory: async_sessionmaker[AsyncSession],
        name: str = "workflow-worker",
        worker_id: str | None = None,
        poll_interval: float | None = None,
        concurrency: int | None = None,
        lease_seconds: float | None = None,
        lease_renewal_seconds: float | None = None,
        retry_policy: TaskRetryPolicy | None = None,
    ) -> None:
        super().__init__(name=name)
        self.engine = engine
        self.session_factory = session_factory
        self.worker_id = worker_id or f"{name}-{uuid.uuid4().hex[:8]}"
        self.poll_interval = (
            poll_interval if poll_interval is not None else settings.task_poll_interval_seconds
        )
        self.concurrency = concurrency if concurrency is not None else settings.worker_concurrency
        self.lease_seconds = (
            lease_seconds if lease_seconds is not None else settings.task_lease_seconds
        )
        self.lease_renewal_seconds = (
            lease_renewal_seconds
            if lease_renewal_seconds is not None
            else settings.task_lease_renewal_seconds
        )
        self.retry_policy = retry_policy or TaskRetryPolicy(
            max_attempts=settings.task_max_attempts,
            base_backoff_seconds=settings.task_retry_backoff_seconds,
        )
        self.lease_manager = LeaseManager(
            worker_id=self.worker_id,
            session_factory=self.session_factory,
            lease_duration_seconds=self.lease_seconds,
            renewal_interval_seconds=self.lease_renewal_seconds,
        )
        self._concurrency_semaphore = asyncio.Semaphore(self.concurrency)
        self._active_task_futures: dict[uuid.UUID, asyncio.Task[Any]] = {}

    @log_errors
    async def submit_task(
        self,
        job_id: uuid.UUID,
        task_type: str = "workflow_step",
        payload: dict[str, Any] | None = None,
        max_attempts: int | None = None,
        workflow_thread_id: str | None = None,
    ) -> Task:
        """Persist a new pending task for execution by this or peer workers."""
        try:
            async with self.session_factory() as session, session.begin():
                repo = TaskRepository(session)
                task = await repo.create_task(
                    job_id=job_id,
                    task_type=task_type,
                    payload=payload,
                    max_attempts=max_attempts or self.retry_policy.max_attempts,
                    workflow_thread_id=workflow_thread_id or str(job_id),
                )
                return task
        except Exception as exc:
            logger.exception("WorkflowWorker.submit_task failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def process_job(
        self,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        owner: str,
        initial_state: ModernizationWorkflowState | None = None,
    ) -> ModernizationWorkflowState:
        """Execute or resume a single modernization job within an isolated database transaction."""
        try:
            async with self.session_factory() as session, session.begin():
                state = await self.engine.start_workflow(
                    job_id=job_id,
                    tenant_id=tenant_id,
                    owner=owner,
                    initial_state=initial_state,
                    session=session,
                )
                return state
        except Exception as exc:
            logger.exception(
                "WorkflowWorker.process_job failed for %s | %s: %s", job_id, type(exc).__name__, exc
            )
            raise

    @log_errors
    async def claim_and_execute_next_task(self) -> uuid.UUID | None:
        """Atomically claim the next eligible task from PostgreSQL and execute it."""
        try:
            task: Task | None = None
            async with self.session_factory() as session, session.begin():
                task = await self.lease_manager.acquire_lease(session)

            if task is None:
                return None

            task_id = task.id
            await self.execute_task(task_id)
            return task_id
        except Exception as exc:
            logger.exception(
                "WorkflowWorker.claim_and_execute_next_task failed | %s: %s",
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def execute_task(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        """Execute a claimed task through LangGraph with lease checks, cancellation checks, and conditional completion."""
        try:
            # 1. Fetch task and check parent job
            async with self.session_factory() as session:
                task_repo = TaskRepository(session)
                job_repo = JobRepository(session)
                task = await task_repo.get_by_id(task_id)
                if task is None:
                    raise LeaseLostError(f"Task {task_id} not found in database")
                job = await job_repo.get_by_id_unscoped(task.job_id)
                if job is None:
                    raise LeaseLostError(f"Job {task.job_id} not found for task {task_id}")

            # 2. Check if job is cancelled before starting work
            if job.status == JobLifecycleState.CANCELLED.value:
                logger.info("Job %s is cancelled; cancelling task %s", job.id, task_id)
                async with self.session_factory() as session, session.begin():
                    task_repo = TaskRepository(session)
                    await task_repo.cancel_task(
                        task_id=task_id,
                        worker_id=self.worker_id,
                        reason="Parent job was cancelled",
                    )
                self.lease_manager.untrack_task(task_id)
                return None

            # 3. Coordinate with LangGraph checkpoint
            action = task.payload.get("action", "start")
            resume_payload = task.payload.get("resume_payload")
            state: ModernizationWorkflowState

            async with self.session_factory() as session, session.begin():
                if action == "resume" and resume_payload:
                    state = await self.engine.resume_workflow(
                        job_id=task.job_id,
                        resume_payload=resume_payload,
                        session=session,
                    )
                else:
                    if job.tenant_id is None:
                        raise ValueError(f"Job {job.id} has no tenant_id")
                    prior_state = await self.engine.get_state(task.job_id)
                    state = await self.engine.start_workflow(
                        job_id=task.job_id,
                        tenant_id=job.tenant_id,
                        owner=job.owner,
                        initial_state=prior_state,
                        session=session,
                    )

            # 4. Check if job was cancelled while workflow step executed
            async with self.session_factory() as session:
                job_repo = JobRepository(session)
                refreshed_job = await job_repo.get_by_id_unscoped(task.job_id)
                if refreshed_job and refreshed_job.status == JobLifecycleState.CANCELLED.value:
                    logger.info(
                        "Job %s was cancelled during execution; cancelling task %s",
                        task.job_id,
                        task_id,
                    )
                    async with self.session_factory() as c_session, c_session.begin():
                        t_repo = TaskRepository(c_session)
                        await t_repo.cancel_task(
                            task_id=task_id,
                            worker_id=self.worker_id,
                            reason="Job was cancelled during execution",
                        )
                    self.lease_manager.untrack_task(task_id)
                    return None

            # 5. Conditional completion: enforce valid lease ownership
            result_payload = {
                "completed_steps": state.get("completed_steps", []),
                "current_gate": state.get("current_gate"),
                "gate_approvals": state.get("gate_approvals", {}),
            }
            async with self.session_factory() as session, session.begin():
                task_repo = TaskRepository(session)
                await task_repo.complete_task(
                    task_id=task_id,
                    worker_id=self.worker_id,
                    result_payload=result_payload,
                )

            # Release task from local lease manager tracking
            self.lease_manager.untrack_task(task_id)
            logger.info("Worker '%s' finalized task %s successfully", self.worker_id, task_id)
            return result_payload

        except LeaseLostError as lease_err:
            logger.warning(
                "Worker '%s' lost lease ownership for task %s: %s",
                self.worker_id,
                task_id,
                lease_err,
            )
            self.lease_manager.untrack_task(task_id)
            raise
        except Exception as exc:
            logger.error(
                "Worker '%s' encountered error executing task %s: %s",
                self.worker_id,
                task_id,
                exc,
            )
            classification = classify_exception(exc)
            try:
                async with self.session_factory() as session, session.begin():
                    task_repo = TaskRepository(session)
                    t = await task_repo.get_by_id(task_id)
                    attempt = t.attempt_count if t else 1
                    backoff = self.retry_policy.get_backoff_seconds(attempt)
                    await task_repo.fail_task(
                        task_id=task_id,
                        worker_id=self.worker_id,
                        error_message=str(exc),
                        classification=classification,
                        retry_backoff_seconds=backoff,
                    )
            except Exception as fail_err:
                logger.warning("Could not record failure state for task %s: %s", task_id, fail_err)
            self.lease_manager.untrack_task(task_id)
            raise

    @log_errors
    async def _execute_with_semaphore(self, task_id: uuid.UUID) -> None:
        """Run task execution under concurrency bounds."""
        async with self._concurrency_semaphore:
            try:
                await self.execute_task(task_id)
            except Exception as exc:
                logger.error("Execution failed for task %s: %s", task_id, exc)
            finally:
                self._active_task_futures.pop(task_id, None)

    @log_errors
    async def recover_active_jobs(self) -> list[uuid.UUID]:
        """Scan PostgreSQL for running or interrupted jobs and safely resume them from durable checkpoints."""
        try:
            recovered_ids: list[uuid.UUID] = []
            async with self.session_factory() as session:
                jobs_repo = JobRepository(session)
                running_jobs = await jobs_repo.list_jobs_unscoped(
                    status=JobLifecycleState.RUNNING.value
                )

            for job in running_jobs:
                if self.should_stop:
                    break
                if job.tenant_id is None:
                    logger.warning("Skipping recovery for job %s with missing tenant_id", job.id)
                    continue

                try:
                    prior_state = await self.engine.get_state(job.id)
                    await self.process_job(
                        job_id=job.id,
                        tenant_id=job.tenant_id,
                        owner=job.owner,
                        initial_state=prior_state,
                    )
                    recovered_ids.append(job.id)
                except Exception as rec_exc:
                    logger.error("Failed to recover job %s: %s", job.id, rec_exc)

            return recovered_ids
        except Exception as exc:
            logger.exception(
                "WorkflowWorker.recover_active_jobs failed | %s: %s", type(exc).__name__, exc
            )
            raise

    @log_errors
    async def _run_loop(self) -> None:
        """Poll and execute workflow tasks and active jobs until cooperative shutdown is signaled."""
        try:
            self.lease_manager.start()
            logger.info("WorkflowWorker '%s' running initial crash-recovery sweep", self.name)
            await self.recover_active_jobs()

            while not self.should_stop:
                try:
                    # Clean up completed tasks
                    finished = [tid for tid, fut in self._active_task_futures.items() if fut.done()]
                    for tid in finished:
                        self._active_task_futures.pop(tid, None)

                    # Bounded concurrency
                    if len(self._active_task_futures) >= self.concurrency:
                        await asyncio.sleep(self.poll_interval)
                        continue

                    # Claim next task
                    claimed_task: Task | None = None
                    async with self.session_factory() as session, session.begin():
                        claimed_task = await self.lease_manager.acquire_lease(session)

                    if claimed_task is None:
                        await asyncio.sleep(self.poll_interval)
                        continue

                    task_id = claimed_task.id
                    fut = asyncio.create_task(
                        self._execute_with_semaphore(task_id),
                        name=f"task-exec-{task_id}",
                    )
                    self._active_task_futures[task_id] = fut

                except asyncio.CancelledError:
                    break
                except Exception as loop_exc:
                    logger.error("Error in WorkflowWorker loop: %s", loop_exc)
                    await asyncio.sleep(self.poll_interval)
        except Exception as exc:
            logger.exception("WorkflowWorker._run_loop failed | %s: %s", type(exc).__name__, exc)
            raise
        finally:
            await self.shutdown()

    @log_errors
    async def shutdown(self, timeout_seconds: float | None = None) -> None:
        """Cooperative shutdown: await in-flight tasks, stop lease renewals, and release abandoned leases."""
        try:
            timeout = (
                timeout_seconds
                if timeout_seconds is not None
                else settings.task_shutdown_grace_seconds
            )
            self._is_running = False
            self.request_stop()
            logger.info(
                "Shutting down WorkflowWorker '%s' (worker_id: %s)...",
                self.name,
                self.worker_id,
            )

            # Wait for active tasks with bounded grace period
            if self._active_task_futures:
                active_list = list(self._active_task_futures.values())
                _done, pending = await asyncio.wait(
                    active_list,
                    timeout=timeout,
                    return_when=asyncio.ALL_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

            # Stop lease renewals so we don't extend abandoned leases
            await self.lease_manager.stop()

            # Release abandoned tasks back to pending for immediate recovery
            abandoned_task_ids = list(self.lease_manager.active_task_ids)
            for tid in abandoned_task_ids:
                try:
                    async with self.session_factory() as session, session.begin():
                        await self.lease_manager.release_lease(session, tid)
                except Exception as rel_exc:
                    logger.warning("Could not release lease on abandoned task %s: %s", tid, rel_exc)

            logger.info("WorkflowWorker '%s' shutdown complete", self.name)
        except Exception as exc:
            logger.exception("WorkflowWorker.shutdown failed | %s: %s", type(exc).__name__, exc)
            raise


__all__ = ["WorkflowWorker"]
