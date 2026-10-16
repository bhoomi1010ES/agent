"""Pydantic transport schemas for Model Gateway, Budgets, and Executions."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from modernization_platform.domain.model_gateway.pricing import microcents_to_cents


class ModelGenerateApiRequest(BaseModel):
    """Client request schema for generating text via the hosted model gateway."""

    agent_role: str = Field(
        ...,
        description="Role of the invoking agent (e.g. architect, analyzer, converter, reviewer)",
    )
    messages: list[dict[str, Any]] = Field(
        ..., min_length=1, description="Standard chat messages list"
    )
    model: str | None = Field(default=None, description="Optional target model identifier")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1000, ge=1, le=128000)
    prompt_version: str = Field(default="v1.0", description="Authoritative prompt template version")
    task_id: uuid.UUID | None = Field(default=None, description="Optional correlated task ID")
    agent_run_id: uuid.UUID | None = Field(
        default=None, description="Optional correlated agent run ID"
    )
    tools: list[dict[str, Any]] | None = Field(
        default=None, description="Optional tool definitions"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional contextual metadata"
    )


class ModelGenerateApiResponse(BaseModel):
    """Response schema returned after model gateway execution."""

    content: str
    provider: str
    model_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_cents: float
    cost_microcents: int
    duration_ms: int
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class BudgetAccountResponse(BaseModel):
    """Response schema representing a durable budget account."""

    id: uuid.UUID
    job_id: uuid.UUID
    scope_type: str
    scope_id: str
    limit_cents: float
    limit_microcents: int
    reserved_cents: float
    reserved_microcents: int
    spent_cents: float
    spent_microcents: int
    remaining_cents: float
    remaining_microcents: int
    warning_threshold_percent: int
    warning_emitted: bool
    hard_stop_percent: int
    currency: str
    status: str

    @classmethod
    def from_orm_model(cls, account: Any) -> "BudgetAccountResponse":
        try:
            spent = account.spent_microcents
            reserved = account.reserved_microcents
            limit = account.limit_microcents
            remaining = max(0, limit - spent - reserved)

            return cls(
                id=account.id,
                job_id=account.job_id,
                scope_type=account.scope_type,
                scope_id=account.scope_id,
                limit_cents=microcents_to_cents(limit),
                limit_microcents=limit,
                reserved_cents=microcents_to_cents(reserved),
                reserved_microcents=reserved,
                spent_cents=microcents_to_cents(spent),
                spent_microcents=spent,
                remaining_cents=microcents_to_cents(remaining),
                remaining_microcents=remaining,
                warning_threshold_percent=account.warning_threshold_percent,
                warning_emitted=account.warning_emitted,
                hard_stop_percent=account.hard_stop_percent,
                currency=account.currency,
                status=account.status,
            )
        except Exception:
            raise


class ModelExecutionResponse(BaseModel):
    """Response schema representing an audited model execution record."""

    id: uuid.UUID
    job_id: uuid.UUID
    task_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None
    provider: str
    model_id: str
    prompt_version: str
    status: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_cents: float
    cost_microcents: int
    duration_ms: int
    tool_call_count: int
    failure_reason: str | None
    input_artifact_ids: list[str]
    output_artifact_ids: list[str]
    created_at: datetime

    @classmethod
    def from_orm_model(cls, execution: Any) -> "ModelExecutionResponse":
        try:
            return cls(
                id=execution.id,
                job_id=execution.job_id,
                task_id=execution.task_id,
                agent_run_id=execution.agent_run_id,
                provider=execution.provider,
                model_id=execution.model_id,
                prompt_version=execution.prompt_version,
                status=execution.status,
                input_tokens=execution.input_tokens,
                output_tokens=execution.output_tokens,
                total_tokens=execution.total_tokens,
                cost_cents=microcents_to_cents(execution.cost_microcents),
                cost_microcents=execution.cost_microcents,
                duration_ms=execution.duration_ms,
                tool_call_count=execution.tool_call_count,
                failure_reason=execution.failure_reason,
                input_artifact_ids=execution.input_artifact_ids or [],
                output_artifact_ids=execution.output_artifact_ids or [],
                created_at=execution.created_at,
            )
        except Exception:
            raise


__all__ = [
    "BudgetAccountResponse",
    "ModelExecutionResponse",
    "ModelGenerateApiRequest",
    "ModelGenerateApiResponse",
]
