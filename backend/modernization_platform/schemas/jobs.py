"""Typed job request, response, status, budget, lifecycle, and pagination contracts."""

import uuid
from typing import Any

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.agent_artifacts.models import TargetStack
from modernization_platform.schemas.base import (
    Identifier,
    ShortText,
    TransportRequest,
    TransportResponse,
)
from modernization_platform.schemas.status import JobStatus


class JobBudget(TransportRequest):
    """Hard job limits supplied at creation time."""

    max_cost_cents: int = Field(gt=0, le=100_000_000)
    max_duration_minutes: int | None = Field(default=None, gt=0, le=525_600)
    max_repair_attempts: int = Field(default=3, ge=1, le=20)


class JobCreateRequest(TransportRequest):
    """Create-job input; authenticated owner identity is intentionally excluded."""

    source_repository: HttpUrl
    source_revision: Identifier
    target_stack: TargetStack
    budget: JobBudget


class JobCreateResponse(TransportResponse):
    """System-assigned identity and initial state returned after job creation."""

    job_id: uuid.UUID
    status: JobStatus
    created_at: AwareDatetime
    version: int = Field(default=1, ge=1)


class JobLifecycleActionRequest(TransportRequest):
    """Payload for lifecycle mutations requiring optimistic concurrency verification."""

    expected_version: int = Field(gt=0, description="Caller's expected version before mutation")
    reason: ShortText | None = Field(
        default=None, description="Optional human or system justification"
    )


class JobLifecycleActionResponse(TransportResponse):
    """Response returned upon successful lifecycle mutation."""

    job_id: uuid.UUID
    status: JobStatus
    version: int = Field(gt=0)
    action: str
    updated_at: AwareDatetime
    message: ShortText | None = None


class JobStatusResponse(TransportResponse):
    """Safe job status response independent from the SQLAlchemy model."""

    job_id: uuid.UUID
    status: JobStatus
    current_stage: Identifier | None = None
    version: int = Field(default=1, ge=1)
    needs_human: bool
    status_message: ShortText | None = None
    failure_classification: ShortText | None = None
    failure_reason: ShortText | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime
    started_at: AwareDatetime | None = None
    paused_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    cancelled_at: AwareDatetime | None = None
    failed_at: AwareDatetime | None = None


class PaginationRequest(TransportRequest):
    """Bounded offset pagination for APIs that expose collections."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class PaginationMetadata(TransportResponse):
    """Pagination information returned alongside a bounded collection."""

    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    total: int = Field(ge=0)

    @model_validator(mode="after")
    @log_errors
    def validate_window(self) -> "PaginationMetadata":
        if self.offset > self.total and self.total != 0:
            raise ValueError("offset cannot exceed total for a non-empty result")
        return self


class JobSummaryResponse(TransportResponse):
    """Summary of a modernization job for list views."""

    job_id: uuid.UUID
    tenant_id: uuid.UUID
    owner_user_id: uuid.UUID
    status: JobStatus
    source_ref: str
    target_stack_spec: dict[str, Any]
    budget: dict[str, Any]
    version: int = Field(default=1, ge=1)
    current_stage: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    finished_at: AwareDatetime | None = None


class JobListResponse(TransportResponse):
    """Bounded, paginated collection of modernization jobs."""

    items: list[JobSummaryResponse]
    pagination: PaginationMetadata


class JobDetailResponse(TransportResponse):
    """Detailed view of a modernization job including configuration and lifecycle."""

    job_id: uuid.UUID
    tenant_id: uuid.UUID
    owner_user_id: uuid.UUID
    status: JobStatus
    source_ref: str
    target_stack_spec: dict[str, Any]
    budget: dict[str, Any]
    version: int = Field(default=1, ge=1)
    current_stage: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    started_at: AwareDatetime | None = None
    paused_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    cancelled_at: AwareDatetime | None = None
    failed_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    failure_reason: str | None = None
    failure_classification: str | None = None


__all__ = [
    "JobBudget",
    "JobCreateRequest",
    "JobCreateResponse",
    "JobDetailResponse",
    "JobLifecycleActionRequest",
    "JobLifecycleActionResponse",
    "JobListResponse",
    "JobStatusResponse",
    "JobSummaryResponse",
    "PaginationMetadata",
    "PaginationRequest",
]
