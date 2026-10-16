"""Dedicated lease manager abstraction for task claiming, automated background renewal, and ownership verification."""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.task import Task
from modernization_platform.repositories.tasks import TaskRepository

logger = logging.getLogger(__name__)


class LeaseManager:
    """Manages worker lease acquisition, automated periodic renewal, and ownership protection."""

    def __init__(
        self,
        worker_id: str,
        session_factory: async_sessionmaker[AsyncSession],
        lease_duration_seconds: float = 30.0,
        renewal_interval_seconds: float = 10.0,
    ) -> None:
        self.worker_id = worker_id
        self.session_factory = session_factory
        self.lease_duration_seconds = lease_duration_seconds
        self.renewal_interval_seconds = renewal_interval_seconds
        self._tracked_tasks: dict[uuid.UUID, Callable[[uuid.UUID], None] | None] = {}
        self._renewal_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def active_task_ids(self) -> set[uuid.UUID]:
        """Set of task IDs currently tracked for automatic lease renewal."""
        return set(self._tracked_tasks.keys())

    @log_errors
    def start(self) -> None:
        """Start the background lease renewal task."""
        try:
            self._stop_event.clear()
            if self._renewal_task is None or self._renewal_task.done():
                self._renewal_task = asyncio.create_task(
                    self._renewal_loop(),
                    name=f"lease-renewal-{self.worker_id}",
                )
                logger.debug("Started lease renewal supervisor for worker '%s'", self.worker_id)
        except Exception as exc:
            logger.exception("LeaseManager.start failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def stop(self) -> None:
        """Cease background lease renewals and wait for supervisor termination."""
        try:
            self._stop_event.set()
            if self._renewal_task and not self._renewal_task.done():
                self._renewal_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._renewal_task
            self._renewal_task = None
            logger.debug("Stopped lease renewal supervisor for worker '%s'", self.worker_id)
        except Exception as exc:
            logger.exception("LeaseManager.stop failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    def track_task(
        self,
        task_id: uuid.UUID,
        on_lease_lost: Callable[[uuid.UUID], None] | None = None,
    ) -> None:
        """Register a task for automated periodic lease renewal."""
        try:
            self._tracked_tasks[task_id] = on_lease_lost
            logger.debug("Worker '%s' tracking task %s for lease renewal", self.worker_id, task_id)
        except Exception as exc:
            logger.exception("LeaseManager.track_task failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    def untrack_task(self, task_id: uuid.UUID) -> None:
        """Remove a task from automated renewal (e.g. after completion or failure)."""
        try:
            self._tracked_tasks.pop(task_id, None)
            logger.debug("Worker '%s' untracked task %s", self.worker_id, task_id)
        except Exception as exc:
            logger.exception("LeaseManager.untrack_task failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def acquire_lease(
        self,
        session: AsyncSession,
        lease_seconds: float | None = None,
        task_types: Sequence[str] | None = None,
        on_lease_lost: Callable[[uuid.UUID], None] | None = None,
    ) -> Task | None:
        """Atomically claim the next claimable task and begin automatic lease renewal."""
        try:
            repo = TaskRepository(session)
            duration = lease_seconds or self.lease_duration_seconds
            task = await repo.claim_next_task(
                worker_id=self.worker_id,
                lease_seconds=duration,
                task_types=task_types,
            )
            if task is not None:
                self.track_task(task.id, on_lease_lost=on_lease_lost)
            return task
        except Exception as exc:
            logger.exception("LeaseManager.acquire_lease failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def renew_lease(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
        extend_seconds: float | None = None,
    ) -> bool:
        """Explicitly renew lease for a task, verifying current ownership."""
        try:
            repo = TaskRepository(session)
            duration = extend_seconds or self.lease_duration_seconds
            success = await repo.renew_lease(
                task_id=task_id,
                worker_id=self.worker_id,
                extend_seconds=duration,
            )
            if not success:
                # Ownership lost, trigger lease lost callback if registered
                callback = self._tracked_tasks.pop(task_id, None)
                if callback is not None:
                    try:
                        callback(task_id)
                    except Exception as cb_exc:
                        logger.error("Error in on_lease_lost callback for %s: %s", task_id, cb_exc)
            return success
        except Exception as exc:
            logger.exception(
                "LeaseManager.renew_lease failed for %s | %s: %s", task_id, type(exc).__name__, exc
            )
            raise

    @log_errors
    async def release_lease(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
    ) -> bool:
        """Safely release the lease on an active task back to pending and remove from tracking."""
        try:
            self.untrack_task(task_id)
            repo = TaskRepository(session)
            return await repo.release_lease(task_id=task_id, worker_id=self.worker_id)
        except Exception as exc:
            logger.exception(
                "LeaseManager.release_lease failed for %s | %s: %s",
                task_id,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def _renewal_loop(self) -> None:
        """Background coroutine periodically extending leases for all currently active tasks."""
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.sleep(self.renewal_interval_seconds)
                except asyncio.CancelledError:
                    break

                if self._stop_event.is_set():
                    break

                task_ids = list(self._tracked_tasks.keys())
                for task_id in task_ids:
                    try:
                        async with self.session_factory() as session, session.begin():
                            renewed = await self.renew_lease(session, task_id)
                            if not renewed:
                                logger.warning(
                                    "Automated lease renewal failed for task %s; worker '%s' lost ownership",
                                    task_id,
                                    self.worker_id,
                                )
                    except Exception as ren_err:
                        logger.error(
                            "LeaseManager exception while renewing task %s for worker '%s': %s",
                            task_id,
                            self.worker_id,
                            ren_err,
                        )
        except Exception as exc:
            logger.exception("LeaseManager._renewal_loop crashed | %s: %s", type(exc).__name__, exc)
            raise


__all__ = ["LeaseManager"]
