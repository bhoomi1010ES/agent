"""Gate repository for managing approval gates and human decisions."""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
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

    async def get_by_id(self, gate_id: uuid.UUID) -> Gate | None:
        """Retrieve a gate by its identifier."""
        try:
            stmt = select(Gate).where(Gate.id == gate_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id", exc) from exc

    async def list_gates_by_job(
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

    async def record_decision(
        self,
        gate_id: uuid.UUID,
        actor: str,
        decision: str,
        feedback: str | None = None,
        waivers: dict[str, Any] | None = None,
        decision_id: uuid.UUID | None = None,
    ) -> GateDecision:
        """Record an immutable human decision and update gate status."""
        try:
            gate = await self.get_by_id(gate_id)
            if gate is None:
                raise ValueError(f"Gate with ID {gate_id} not found")

            gate_dec = GateDecision(
                id=decision_id or uuid.uuid4(),
                gate_id=gate_id,
                actor=actor,
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
            await self.session.flush()
            return gate_dec
        except Exception as exc:
            raise self._translate_error("record_decision", exc) from exc
