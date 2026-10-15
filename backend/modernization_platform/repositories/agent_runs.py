"""AgentRun repository for recording agent invocations, tokens, cost, and tool calls."""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.agent_run import AgentRun
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class AgentRunRepository(BaseRepository[AgentRun]):
    """Repository operations for AgentRun entity (append-only telemetry/audit)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def record_run(
        self,
        job_id: uuid.UUID,
        agent: str,
        model: str,
        prompt_version: str,
        input_artifact_ids: list[str] | None = None,
        output_artifact_ids: list[str] | None = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
        cost_cents: float = 0.0,
        duration_ms: int = 0,
        tool_calls: list[dict[str, Any]] | None = None,
        module_attempt_id: uuid.UUID | None = None,
        step_key: str | None = None,
        run_id: uuid.UUID | None = None,
    ) -> AgentRun:
        """Record an immutable agent step execution."""
        try:
            run = AgentRun(
                id=run_id or uuid.uuid4(),
                job_id=job_id,
                module_attempt_id=module_attempt_id,
                agent=agent,
                step_key=step_key,
                model=model,
                prompt_version=prompt_version,
                input_artifact_ids=input_artifact_ids or [],
                output_artifact_ids=output_artifact_ids or [],
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                cost_cents=cost_cents,
                duration_ms=duration_ms,
                tool_calls=tool_calls or [],
            )
            self.session.add(run)
            await self.session.flush()
            return run
        except Exception as exc:
            raise self._translate_error("record_run", exc) from exc

    async def get_by_id(self, run_id: uuid.UUID) -> AgentRun | None:
        """Retrieve an agent run record by ID."""
        try:
            stmt = select(AgentRun).where(AgentRun.id == run_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id", exc) from exc

    async def list_runs_by_job(
        self,
        job_id: uuid.UUID,
        agent: str | None = None,
    ) -> list[AgentRun]:
        """List all agent runs for a job in chronological order."""
        try:
            stmt = (
                select(AgentRun)
                .where(AgentRun.job_id == job_id)
                .order_by(AgentRun.created_at.asc())
            )
            if agent:
                stmt = stmt.where(AgentRun.agent == agent)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_runs_by_job", exc) from exc
