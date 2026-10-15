"""Job repository for managing modernization job records."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
        job_id: uuid.UUID | None = None,
    ) -> Job:
        """Create and persist a new modernization job record."""
        try:
            job = Job(
                id=job_id or uuid.uuid4(),
                owner=owner,
                source_ref=source_ref,
                target_stack_spec=target_stack_spec or {},
                budget=budget or {},
                status="pending",
            )
            self.session.add(job)
            await self.session.flush()
            return job
        except Exception as exc:
            raise self._translate_error("create_job", exc) from exc

    async def get_by_id(self, job_id: uuid.UUID) -> Job | None:
        """Retrieve a job by its unique identifier."""
        try:
            stmt = select(Job).where(Job.id == job_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id", exc) from exc

    async def list_jobs(
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
            job = await self.get_by_id(job_id)
            if job is None:
                return None
            job.status = status
            if finished:
                job.finished_at = datetime.now(UTC)
            await self.session.flush()
            return job
        except Exception as exc:
            raise self._translate_error("update_status", exc) from exc
