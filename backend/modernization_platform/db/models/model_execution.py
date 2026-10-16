"""SQLAlchemy ORM model for hosted model execution tracking and auditability."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modernization_platform.db.base import Base
from modernization_platform.db.types import GUID, UTCDateTime

if TYPE_CHECKING:
    from modernization_platform.db.models.agent_run import AgentRun
    from modernization_platform.db.models.artifact import Artifact
    from modernization_platform.db.models.job import Job
    from modernization_platform.db.models.task import Task


class ModelExecution(Base):
    """Immutable audit, telemetry, cost, and usage record for every hosted model invocation."""

    __tablename__ = "model_execution"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique model execution identifier",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent modernization job",
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("task.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional durable background task boundary",
    )
    workflow_thread_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="LangGraph durable checkpoint thread identifier",
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("agent_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Associated agent run record",
    )
    agent_role: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Agent role making the call (architect, analyzer, converter, reviewer...)",
    )
    module: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Module context if invocation is scoped to a specific code module",
    )
    stage: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Workflow stage (intake, analysis, architecture, conversion, verification)",
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Model provider used (mock, qwen, anthropic, openai, openrouter, azure)",
    )
    model_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Configured model identifier invoked",
    )
    prompt_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Version of prompt/template utilized",
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Metered prompt tokens consumed",
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Metered completion tokens generated",
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total token sum (input + output)",
    )
    estimated_cost_microcents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="Pre-call estimated cost in integer microcents",
    )
    actual_cost_microcents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="Reconciled financial cost in integer microcents",
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Wall clock duration of the invocation in milliseconds",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="success",
        index=True,
        comment="Execution status: success, failed, timeout, policy_violation, budget_exceeded",
    )
    failure_classification: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Error classification if status != success",
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Retry attempt count",
    )
    is_fallback: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True if request was served by an approved fallback model",
    )
    primary_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Primary provider that failed if fallback was activated",
    )
    primary_model_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Primary model that failed if fallback was activated",
    )
    fallback_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Reason or error why fallback was triggered",
    )
    tool_call_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of tool calls produced in response",
    )
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Redacted metadata of tool calls",
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("artifact.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Associated artifact produced or influenced by this invocation",
    )
    artifact_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Version of the associated artifact",
    )
    correlation_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Tracing correlation ID for request observability",
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        comment="Timestamp when model execution occurred",
    )

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="model_executions")
    task: Mapped["Task | None"] = relationship("Task")
    agent_run: Mapped["AgentRun | None"] = relationship("AgentRun")
    artifact: Mapped["Artifact | None"] = relationship("Artifact")

    __table_args__ = (
        Index("ix_model_exec_job_created", "job_id", "created_at"),
        Index("ix_model_exec_provider_model", "provider", "model_id"),
        Index("ix_model_exec_agent_stage", "agent_role", "stage"),
    )


__all__ = ["ModelExecution"]
