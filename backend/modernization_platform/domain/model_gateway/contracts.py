"""Provider-neutral request, response, and execution context domain models."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modernization_platform.domain.model_gateway.pricing import (
    microcents_to_cents,
)


class ChatMessage(BaseModel):
    """Provider-neutral chat message contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ToolDefinition(BaseModel):
    """Schema definition of a tool/function available to the model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """Structured tool execution request emitted by a model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    arguments: dict[str, Any] | str


class ModelRequest(BaseModel):
    """Model-independent request contract provided by workflow agents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: list[ChatMessage]
    prompt_version: str = Field(min_length=1, max_length=100)
    model: str | None = None  # None indicates gateway policy selects model
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=2048, ge=1, le=32768)
    max_output_tokens: int | None = Field(default=None)
    tools: list[ToolDefinition] = Field(default_factory=list)
    response_format: Literal["text", "json_object"] = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _sync_max_tokens(cls, data: Any) -> Any:
        try:
            if isinstance(data, dict):
                if "max_output_tokens" in data and "max_tokens" not in data:
                    data["max_tokens"] = data["max_output_tokens"]
                elif "max_tokens" in data and "max_output_tokens" not in data:
                    data["max_output_tokens"] = data["max_tokens"]
            return data
        except Exception:
            return data


@dataclass(frozen=True)
class ModelExecutionContext:
    """Authoritative server-side execution context for an invocation."""

    job_id: uuid.UUID
    agent_role: str
    stage: str = "execution"
    tenant_id: uuid.UUID | None = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: uuid.UUID | None = None
    workflow_thread_id: str | None = None
    agent_run_id: uuid.UUID | None = None
    module: str | None = None
    artifact_id: uuid.UUID | None = None
    artifact_version: int | None = None


@dataclass
class UsageMetrics:
    """Token consumption, latency, and financial cost metrics."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_microcents: int = 0
    actual_cost_microcents: int = 0
    duration_ms: int = 0

    @property
    def estimated_cost_cents(self) -> float:
        return microcents_to_cents(self.estimated_cost_microcents)

    @property
    def actual_cost_cents(self) -> float:
        return microcents_to_cents(self.actual_cost_microcents)


@dataclass
class ModelResponse:
    """Provider-neutral model execution result."""

    content: str
    model_id: str
    provider: str
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    raw_response: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


__all__ = [
    "ChatMessage",
    "ModelExecutionContext",
    "ModelRequest",
    "ModelResponse",
    "ToolCall",
    "ToolDefinition",
    "UsageMetrics",
]
