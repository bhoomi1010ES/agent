"""Unit tests for Job schemas and validation rules."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from modernization_platform.schemas.jobs import (
    JobBudget,
    JobCreateRequest,
    JobCreateResponse,
    JobDetailResponse,
    JobLifecycleActionRequest,
    JobLifecycleActionResponse,
    JobListResponse,
    JobStatusResponse,
    JobSummaryResponse,
    PaginationMetadata,
    PaginationRequest,
)
from modernization_platform.schemas.status import JobStatus


def test_job_budget_valid() -> None:
    budget = JobBudget(
        max_cost_cents=50000,
        max_duration_minutes=120,
        max_repair_attempts=3,
    )
    assert budget.max_cost_cents == 50000
    assert budget.max_duration_minutes == 120
    assert budget.max_repair_attempts == 3


def test_job_budget_validation_errors() -> None:
    with pytest.raises(ValidationError):
        JobBudget(max_cost_cents=0)  # gt=0

    with pytest.raises(ValidationError):
        JobBudget(max_cost_cents=-10)

    with pytest.raises(ValidationError):
        JobBudget(max_cost_cents=100_000_001)  # le=100_000_000

    with pytest.raises(ValidationError):
        JobBudget(max_cost_cents=1000, max_repair_attempts=0)  # ge=1

    with pytest.raises(ValidationError):
        JobBudget(max_cost_cents=1000, max_repair_attempts=25)  # le=20


def test_job_create_request_valid() -> None:
    req = JobCreateRequest(
        source_repository="https://github.com/org/repo",  # type: ignore[arg-type]
        source_revision="v1.0.0",
        target_stack={"language": "python", "framework": "fastapi"},  # type: ignore[arg-type]
        budget=JobBudget(max_cost_cents=10000),
    )
    assert str(req.source_repository) == "https://github.com/org/repo"
    assert req.source_revision == "v1.0.0"
    assert req.budget.max_cost_cents == 10000


def test_job_create_request_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(
            source_repository="https://github.com/org/repo",  # type: ignore[arg-type]
            source_revision="v1.0.0",
            target_stack={"language": "python"},  # type: ignore[arg-type]
            budget=JobBudget(max_cost_cents=10000),
            tenant_id=uuid.uuid4(),  # type: ignore[call-arg]
        )


def test_job_create_response_defaults() -> None:
    job_id = uuid.uuid4()
    now = datetime.now(UTC)
    resp = JobCreateResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        created_at=now,
    )
    assert resp.job_id == job_id
    assert resp.status == JobStatus.QUEUED
    assert resp.version == 1


def test_job_lifecycle_action_request() -> None:
    req = JobLifecycleActionRequest(expected_version=2, reason="Maintenance pause")
    assert req.expected_version == 2
    assert req.reason == "Maintenance pause"

    with pytest.raises(ValidationError):
        JobLifecycleActionRequest(expected_version=0)  # gt=0


def test_job_lifecycle_action_response() -> None:
    job_id = uuid.uuid4()
    now = datetime.now(UTC)
    resp = JobLifecycleActionResponse(
        job_id=job_id,
        status=JobStatus.PAUSED,
        version=3,
        action="pause",
        updated_at=now,
        message="Job paused successfully",
    )
    assert resp.job_id == job_id
    assert resp.status == JobStatus.PAUSED
    assert resp.version == 3
    assert resp.action == "pause"


def test_job_status_response_fields() -> None:
    job_id = uuid.uuid4()
    now = datetime.now(UTC)
    resp = JobStatusResponse(
        job_id=job_id,
        status=JobStatus.RUNNING,
        current_stage="analysis",
        version=2,
        needs_human=False,
        status_message="Stage in progress",
        updated_at=now,
        started_at=now,
    )
    assert resp.job_id == job_id
    assert resp.status == JobStatus.RUNNING
    assert resp.current_stage == "analysis"
    assert resp.version == 2
    assert resp.needs_human is False
    assert resp.started_at == now


def test_pagination_request_validation() -> None:
    p = PaginationRequest(offset=10, limit=25)
    assert p.offset == 10
    assert p.limit == 25

    with pytest.raises(ValidationError):
        PaginationRequest(offset=-1)

    with pytest.raises(ValidationError):
        PaginationRequest(limit=0)

    with pytest.raises(ValidationError):
        PaginationRequest(limit=201)  # le=200


def test_pagination_metadata_validation() -> None:
    meta = PaginationMetadata(offset=0, limit=50, total=100)
    assert meta.offset == 0
    assert meta.total == 100

    # offset > total when total > 0 raises ValueError
    with pytest.raises(ValidationError):
        PaginationMetadata(offset=150, limit=50, total=100)

    # offset > 0 when total == 0 is permitted (empty window)
    empty_meta = PaginationMetadata(offset=10, limit=50, total=0)
    assert empty_meta.total == 0


def test_job_summary_and_list_response() -> None:
    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    summary = JobSummaryResponse(
        job_id=job_id,
        tenant_id=tenant_id,
        owner_user_id=user_id,
        status=JobStatus.QUEUED,
        source_ref="https://github.com/org/repo@main",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 10000},
        version=1,
        current_stage=None,
        created_at=now,
        updated_at=now,
    )
    assert summary.job_id == job_id
    assert summary.version == 1

    list_resp = JobListResponse(
        items=[summary],
        pagination=PaginationMetadata(offset=0, limit=10, total=1),
    )
    assert len(list_resp.items) == 1
    assert list_resp.pagination.total == 1


def test_job_detail_response() -> None:
    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    detail = JobDetailResponse(
        job_id=job_id,
        tenant_id=tenant_id,
        owner_user_id=user_id,
        status=JobStatus.FAILED,
        source_ref="https://github.com/org/repo@main",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 10000},
        version=4,
        current_stage="code_generation",
        created_at=now,
        updated_at=now,
        started_at=now,
        failed_at=now,
        finished_at=now,
        failure_reason="Syntax validation failed",
        failure_classification="terminal",
    )
    assert detail.job_id == job_id
    assert detail.status == JobStatus.FAILED
    assert detail.failure_classification == "terminal"
    assert detail.failure_reason == "Syntax validation failed"
