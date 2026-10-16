"""Job repository for managing modernization job records with optimistic concurrency."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.identity import JobMember
from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.errors import (
    JobConcurrencyConflictError,
    JobNotFoundError,
)
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class JobRepository(BaseRepository[Job]):
    """Repository operations for Job entity supporting concurrency and lifecycle tracking."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @log_errors
    async def create_job(
        self,
        owner: str,
        source_ref: str,
        target_stack_spec: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        tenant_id: uuid.UUID | None = None,
        owner_user_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        status: str = "queued",
        source_revision: str | None = None,
        current_stage: str | None = None,
    ) -> Job:
        """Create and persist a new modernization job record with initial lifecycle state."""
        try:
            now = datetime.now(UTC)
            job = Job(
                id=job_id or uuid.uuid4(),
                owner=owner,
                source_ref=source_ref,
                source_revision=source_revision,
                target_stack_spec=target_stack_spec or {},
                budget=budget or {},
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                status=status,
                version=1,
                current_stage=current_stage or "queued",
                created_at=now,
                updated_at=now,
            )
            self.session.add(job)
            await self.session.flush()
            return job
        except Exception as exc:
            raise self._translate_error("create_job", exc) from exc

    @log_errors
    async def _get_by_id_unscoped(self, job_id: uuid.UUID) -> Job | None:
        """Internal lookup for repository mutations after authorization."""
        try:
            stmt = select(Job).where(Job.id == job_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("_get_by_id_unscoped", exc) from exc

    @log_errors
    async def get_by_id_scoped(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
        for_update: bool = False,
    ) -> Job | None:
        """Retrieve a job only within explicit tenant and job-membership scope."""
        try:
            statement = select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
            if not tenant_admin:
                member_access = (
                    select(JobMember.id)
                    .where(
                        JobMember.job_id == Job.id,
                        JobMember.membership_id == membership_id,
                    )
                    .exists()
                )
                statement = statement.where((Job.owner_user_id == user_id) | member_access)
            if for_update:
                statement = statement.with_for_update()
            result = await self.session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id_scoped", exc) from exc

    @log_errors
    async def update_lifecycle_state(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool,
        expected_version: int,
        new_status: str,
        current_stage: str | None = None,
        started_at: datetime | None = None,
        paused_at: datetime | None = None,
        completed_at: datetime | None = None,
        cancelled_at: datetime | None = None,
        failed_at: datetime | None = None,
        finished_at: datetime | None = None,
        failure_reason: str | None = None,
        failure_classification: str | None = None,
    ) -> Job:
        """Atomically transition job lifecycle state with optimistic concurrency verification."""
        try:
            job = await self.get_by_id_scoped(
                job_id=job_id,
                tenant_id=tenant_id,
                user_id=user_id,
                membership_id=membership_id,
                tenant_admin=tenant_admin,
                for_update=True,
            )
            if job is None:
                raise JobNotFoundError(str(job_id))

            if job.version != expected_version:
                logger.warning(
                    "Optimistic concurrency conflict on job update | job_id=%s expected_version=%d actual_version=%d",
                    job_id,
                    expected_version,
                    job.version,
                )
                raise JobConcurrencyConflictError(
                    expected_version=expected_version,
                    actual_version=job.version,
                )

            now = datetime.now(UTC)
            job.status = new_status
            job.version = job.version + 1
            job.updated_at = now

            if current_stage is not None:
                job.current_stage = current_stage
            if started_at is not None:
                job.started_at = started_at
            if paused_at is not None:
                job.paused_at = paused_at
            if completed_at is not None:
                job.completed_at = completed_at
            if cancelled_at is not None:
                job.cancelled_at = cancelled_at
            if failed_at is not None:
                job.failed_at = failed_at
            if finished_at is not None:
                job.finished_at = finished_at
            if failure_reason is not None:
                job.failure_reason = failure_reason
            if failure_classification is not None:
                job.failure_classification = failure_classification

            await self.session.flush()
            return job
        except (JobNotFoundError, JobConcurrencyConflictError):
            raise
        except Exception as exc:
            raise self._translate_error("update_lifecycle_state", exc) from exc

    @log_errors
    async def list_jobs_scoped(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[Job]:
        """List jobs visible to the principal within their authorized tenant scope."""
        try:
            statement = select(Job).where(Job.tenant_id == tenant_id)
            if not tenant_admin:
                member_access = (
                    select(JobMember.id)
                    .where(
                        JobMember.job_id == Job.id,
                        JobMember.membership_id == membership_id,
                    )
                    .exists()
                )
                statement = statement.where((Job.owner_user_id == user_id) | member_access)
            if status is not None:
                statement = statement.where(Job.status == status)
            statement = (
                statement.order_by(Job.created_at.desc(), Job.id.desc())
                .limit(min(limit, 100))
                .offset(max(offset, 0))
            )
            result = await self.session.execute(statement)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_jobs_scoped", exc) from exc

    @log_errors
    async def count_jobs_scoped(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
        status: str | None = None,
    ) -> int:
        """Count total jobs visible to the principal within their authorized tenant scope."""
        try:
            statement = select(func.count(Job.id)).where(Job.tenant_id == tenant_id)
            if not tenant_admin:
                member_access = (
                    select(JobMember.id)
                    .where(
                        JobMember.job_id == Job.id,
                        JobMember.membership_id == membership_id,
                    )
                    .exists()
                )
                statement = statement.where((Job.owner_user_id == user_id) | member_access)
            if status is not None:
                statement = statement.where(Job.status == status)
            result = await self.session.execute(statement)
            return int(result.scalar() or 0)
        except Exception as exc:
            raise self._translate_error("count_jobs_scoped", exc) from exc

    @log_errors
    async def _list_jobs_unscoped(
        self,
        limit: int = 50,
        offset: int = 0,
        owner: str | None = None,
        status: str | None = None,
    ) -> list[Job]:
        """List jobs with bounded pagination and optional filtering."""
        try:
            stmt = (
                select(Job)
                .order_by(Job.created_at.desc())
                .limit(min(limit, 100))
                .offset(max(offset, 0))
            )
            if owner:
                stmt = stmt.where(Job.owner == owner)
            if status:
                stmt = stmt.where(Job.status == status)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_jobs", exc) from exc

    @log_errors
    async def update_status(
        self,
        job_id: uuid.UUID,
        status: str,
        finished: bool = False,
    ) -> Job | None:
        """Update job lifecycle status and record finished_at if terminal."""
        try:
            job = await self._get_by_id_unscoped(job_id)
            if job is None:
                return None
            job.status = status
            if finished:
                job.finished_at = datetime.now(UTC)
            await self.session.flush()
            return job
        except Exception as exc:
            raise self._translate_error("update_status", exc) from exc

    @log_errors
    async def get_by_id_unscoped(self, job_id: uuid.UUID) -> Job | None:
        """Internal/service lookup for repository mutations after authorization."""
        try:
            return await self._get_by_id_unscoped(job_id)
        except Exception as exc:
            raise self._translate_error("get_by_id_unscoped", exc) from exc

    @log_errors
    async def list_jobs_unscoped(
        self,
        limit: int = 50,
        offset: int = 0,
        owner: str | None = None,
        status: str | None = None,
    ) -> list[Job]:
        """Internal/worker lookup for active jobs requiring processing or recovery."""
        try:
            return await self._list_jobs_unscoped(
                limit=limit, offset=offset, owner=owner, status=status
            )
        except Exception as exc:
            raise self._translate_error("list_jobs_unscoped", exc) from exc


__all__ = ["JobRepository"]
