"""AuditEvent repository for append-only audit logging."""

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.audit_event import AuditEvent
from modernization_platform.db.models.identity import JobMember
from modernization_platform.db.models.job import Job
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class AuditEventRepository(BaseRepository[AuditEvent]):
    """Repository operations for AuditEvent entity. Strictly append-only (no update/delete)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def append_event(
        self,
        actor: str,
        action: str,
        actor_user_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
        job_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
        event_version: int = 1,
        event_id: uuid.UUID | None = None,
    ) -> AuditEvent:
        """Append an immutable audit event."""
        try:
            event = AuditEvent(
                id=event_id or uuid.uuid4(),
                job_id=job_id,
                actor=actor,
                actor_user_id=actor_user_id,
                action=action,
                correlation_id=correlation_id,
                payload=payload or {},
                event_version=event_version,
            )
            self.session.add(event)
            await self.session.flush()
            return event
        except Exception as exc:
            raise self._translate_error("append_event", exc) from exc

    async def get_by_id(self, event_id: uuid.UUID) -> AuditEvent | None:
        """Retrieve an audit event by identifier."""
        try:
            stmt = select(AuditEvent).where(AuditEvent.id == event_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id", exc) from exc

    async def list_events_by_job(
        self,
        job_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        """List audit events associated with a job in chronological order."""
        try:
            stmt = (
                select(AuditEvent)
                .where(AuditEvent.job_id == job_id)
                .order_by(AuditEvent.event_time.asc())
                .limit(min(limit, 200))
                .offset(max(offset, 0))
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_events_by_job", exc) from exc

    async def list_events_by_job_scoped(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        """List audit events for a job within authorized tenant and membership scope."""
        try:
            statement = (
                select(AuditEvent)
                .join(Job, Job.id == AuditEvent.job_id)
                .where(AuditEvent.job_id == job_id, Job.tenant_id == tenant_id)
            )
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
            statement = (
                statement.order_by(AuditEvent.event_time.asc(), AuditEvent.id.asc())
                .limit(min(limit, 200))
                .offset(max(offset, 0))
            )
            result = await self.session.execute(statement)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_events_by_job_scoped", exc) from exc

    async def count_events_by_job_scoped(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
    ) -> int:
        """Count audit events for a job within authorized tenant and membership scope."""
        try:
            statement = (
                select(func.count(AuditEvent.id))
                .join(Job, Job.id == AuditEvent.job_id)
                .where(AuditEvent.job_id == job_id, Job.tenant_id == tenant_id)
            )
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
            return int(result.scalar() or 0)
        except Exception as exc:
            raise self._translate_error("count_events_by_job_scoped", exc) from exc

    async def list_events(
        self,
        limit: int = 100,
        offset: int = 0,
        action: str | None = None,
        actor: str | None = None,
    ) -> list[AuditEvent]:
        """List audit events across the platform with optional action or actor filters."""
        try:
            stmt = (
                select(AuditEvent)
                .order_by(AuditEvent.event_time.desc())
                .limit(min(limit, 200))
                .offset(max(offset, 0))
            )
            if action:
                stmt = stmt.where(AuditEvent.action == action)
            if actor:
                stmt = stmt.where(AuditEvent.actor == actor)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_events", exc) from exc
