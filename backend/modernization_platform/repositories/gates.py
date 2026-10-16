"""Gate repository for managing approval gates and human decisions."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.db.models.identity import JobMember
from modernization_platform.db.models.job import Job
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class GateRepository(BaseRepository[Gate]):
    """Repository operations for Gate and GateDecision entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def create_gate(
        self,
        job_id: uuid.UUID,
        gate_type: str,
        artifact_versions_shown: dict[str, Any] | None = None,
        needs_human_flags: list[dict[str, Any]] | None = None,
        budget_used_cents: float = 0.0,
        gate_id: uuid.UUID | None = None,
    ) -> Gate:
        """Create a new human-in-the-loop approval gate."""
        try:
            gate = Gate(
                id=gate_id or uuid.uuid4(),
                job_id=job_id,
                gate_type=gate_type,
                state="pending",
                artifact_versions_shown=artifact_versions_shown or {},
                needs_human_flags=needs_human_flags or [],
                budget_used_cents=budget_used_cents,
            )
            self.session.add(gate)
            await self.session.flush()
            return gate
        except Exception as exc:
            raise self._translate_error("create_gate", exc) from exc

    async def _get_by_id_unscoped(self, gate_id: uuid.UUID) -> Gate | None:
        """Internal lookup for persistence workflows after authorization."""
        try:
            stmt = select(Gate).where(Gate.id == gate_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("_get_by_id_unscoped", exc) from exc

    async def get_by_id_scoped(
        self,
        *,
        gate_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
        for_update: bool = False,
    ) -> Gate | None:
        """Retrieve a gate only through its authorized parent job scope."""
        try:
            statement = (
                select(Gate)
                .join(Job, Job.id == Gate.job_id)
                .where(Gate.id == gate_id, Job.tenant_id == tenant_id)
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
            if for_update:
                statement = statement.with_for_update(of=Gate)
            result = await self.session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id_scoped", exc) from exc

    async def list_gates_by_job_scoped(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
        state: str | None = None,
    ) -> list[Gate]:
        """List gates for a job scoped to tenant and user permissions."""
        try:
            statement = (
                select(Gate)
                .join(Job, Job.id == Gate.job_id)
                .where(Gate.job_id == job_id, Job.tenant_id == tenant_id)
                .order_by(Gate.requested_at.asc())
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
            if state:
                statement = statement.where(Gate.state == state)
            result = await self.session.execute(statement)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_gates_by_job_scoped", exc) from exc

    async def _list_gates_by_job_unscoped(
        self,
        job_id: uuid.UUID,
        state: str | None = None,
    ) -> list[Gate]:
        """List all gates for a job ordered by requested timestamp."""
        try:
            stmt = select(Gate).where(Gate.job_id == job_id).order_by(Gate.requested_at.asc())
            if state:
                stmt = stmt.where(Gate.state == state)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_gates_by_job", exc) from exc

    async def record_authorized_decision(
        self,
        gate: Gate,
        actor_user_id: uuid.UUID,
        decision: str,
        feedback: str | None = None,
        waivers: dict[str, Any] | None = None,
        decision_id: uuid.UUID | None = None,
    ) -> GateDecision:
        """Record a decision for a gate already obtained by a scoped authorization query."""
        try:
            gate_dec = GateDecision(
                id=decision_id or uuid.uuid4(),
                gate_id=gate.id,
                actor=str(actor_user_id),
                actor_user_id=actor_user_id,
                decision=decision,
                feedback=feedback,
                waivers=waivers,
            )
            self.session.add(gate_dec)

            # Update parent gate state
            gate.state = (
                "approved"
                if decision == "approved"
                else ("waived" if decision == "waived" else "rejected")
            )
            gate.resolved_at = datetime.now(UTC)
            await self.session.flush()
            return gate_dec
        except Exception as exc:
            raise self._translate_error("record_authorized_decision", exc) from exc
