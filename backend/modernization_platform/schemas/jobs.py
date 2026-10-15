"""Typed job request, response, status, budget, and pagination contracts."""

import uuid

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


class JobStatusResponse(TransportResponse):
    """Safe job status response independent from the SQLAlchemy model."""

    job_id: uuid.UUID
    status: JobStatus
    current_stage: Identifier | None = None
    needs_human: bool
    status_message: ShortText | None = None
    updated_at: AwareDatetime


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
