"""SQLAlchemy repository for hosted model execution records and audit trails."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.core.exceptions import ApplicationException
from modernization_platform.db.models.model_execution import ModelExecution

logger = logging.getLogger(__name__)


class ModelExecutionRepository:
    """PostgreSQL repository handling durable model execution records and audit history."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @log_errors
    def _translate_error(self, operation: str, exc: Exception) -> Exception:
        """Translate repository exceptions into structured platform errors."""
        logger.exception(
            "ModelExecutionRepository.%s failed | %s: %s", operation, type(exc).__name__, exc
        )
        if isinstance(exc, ApplicationException):
            return exc
        return ApplicationException(
            message=f"Model execution repository operation '{operation}' failed: {exc}",
            code="MODEL_EXECUTION_REPOSITORY_ERROR",
        )

    @log_errors
    async def record_execution(
        self,
        *,
        execution_id: uuid.UUID | None = None,
        job_id: uuid.UUID,
        agent_role: str,
        stage: str,
        provider: str,
        model_id: str,
        prompt_version: str,
        correlation_id: str,
        task_id: uuid.UUID | None = None,
        workflow_thread_id: str | None = None,
        agent_run_id: uuid.UUID | None = None,
        module: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_microcents: int = 0,
        actual_cost_microcents: int = 0,
        duration_ms: int = 0,
        status: str = "success",
        failure_classification: str | None = None,
        attempt_number: int = 1,
        is_fallback: bool = False,
        primary_provider: str | None = None,
        primary_model_id: str | None = None,
        fallback_reason: str | None = None,
        tool_call_count: int = 0,
        tool_calls: list[dict[str, Any]] | None = None,
        artifact_id: uuid.UUID | None = None,
        artifact_version: int | None = None,
    ) -> ModelExecution:
        """Persist an immutable model execution record."""
        try:
            total_tokens = input_tokens + output_tokens
            record = ModelExecution(
                id=execution_id or uuid.uuid4(),
                job_id=job_id,
                task_id=task_id,
                workflow_thread_id=workflow_thread_id,
                agent_run_id=agent_run_id,
                agent_role=agent_role,
                module=module,
                stage=stage,
                provider=provider,
                model_id=model_id,
                prompt_version=prompt_version,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost_microcents=estimated_cost_microcents,
                actual_cost_microcents=actual_cost_microcents,
                duration_ms=duration_ms,
                status=status,
                failure_classification=failure_classification,
                attempt_number=attempt_number,
                is_fallback=is_fallback,
                primary_provider=primary_provider,
                primary_model_id=primary_model_id,
                fallback_reason=fallback_reason,
                tool_call_count=tool_call_count,
                tool_calls=tool_calls or [],
                artifact_id=artifact_id,
                artifact_version=artifact_version,
                correlation_id=correlation_id,
                created_at=datetime.now(UTC),
            )
            self.session.add(record)
            await self.session.flush()
            return record
        except Exception as exc:
            raise self._translate_error("record_execution", exc) from exc

    @log_errors
    async def get_by_id(self, execution_id: uuid.UUID) -> ModelExecution | None:
        """Lookup execution record by primary key."""
        try:
            stmt = select(ModelExecution).where(ModelExecution.id == execution_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id", exc) from exc

    @log_errors
    async def list_for_job(
        self,
        job_id: uuid.UUID,
        status: str | None = None,
        provider: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModelExecution]:
        """List execution records for a job ordered chronologically."""
        try:
            stmt = select(ModelExecution).where(ModelExecution.job_id == job_id)
            if status is not None:
                stmt = stmt.where(ModelExecution.status == status)
            if provider is not None:
                stmt = stmt.where(ModelExecution.provider == provider)
            stmt = stmt.order_by(ModelExecution.created_at.desc()).limit(limit).offset(offset)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_for_job", exc) from exc

    list_executions_by_job = list_for_job

    @log_errors
    async def list_for_artifact(
        self,
        artifact_id: uuid.UUID,
    ) -> list[ModelExecution]:
        """Audit trail: find model executions that produced or influenced a specific artifact."""
        try:
            stmt = (
                select(ModelExecution)
                .where(ModelExecution.artifact_id == artifact_id)
                .order_by(ModelExecution.created_at.asc())
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_for_artifact", exc) from exc


__all__ = ["ModelExecutionRepository"]
