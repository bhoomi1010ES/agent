"""Job repository for managing modernization job records."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.identity import JobMember
from modernization_platform.db.models.job import Job
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class JobRepository(BaseRepository[Job]):
    """Repository operations for Job entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def create_job(
        self,
        owner: str,
        source_ref: str,
        target_stack_spec: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        tenant_id: uuid.UUID | None = None,
        owner_user_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
    ) -> Job:
        """Create and persist a new modernization job record."""
        try:
            now = datetime.now(UTC)
            job = Job(
                id=job_id or uuid.uuid4(),
                owner=owner,
                source_ref=source_ref,
                target_stack_spec=target_stack_spec or {},
                budget=budget or {},
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            self.session.add(job)
            await self.session.flush()
            return job
        except Exception as exc:
            raise self._translate_error("create_job", exc) from exc

    async def _get_by_id_unscoped(self, job_id: uuid.UUID) -> Job | None:
        """Internal lookup for repository mutations after authorization."""
        try:
            stmt = select(Job).where(Job.id == job_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("_get_by_id_unscoped", exc) from exc

    async def get_by_id_scoped(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
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
            result = await self.session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id_scoped", exc) from exc

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
