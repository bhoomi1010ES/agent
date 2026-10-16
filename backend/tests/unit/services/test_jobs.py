"""Unit tests for JobService business logic, lifecycle transitions, idempotency, and concurrency."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.errors import (
    IdempotencyConflictError,
    JobConcurrencyConflictError,
    JobNotFoundError,
    TerminalJobMutationError,
)
from modernization_platform.domain.jobs.states import (
    FailureClassification,
    JobLifecycleState,
)
from modernization_platform.repositories.idempotency import compute_request_hash
from modernization_platform.schemas.status import JobStatus
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.jobs import JobService


def _test_principal(
    role: Role = Role.OWNER,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="test-architect",
        issuer="https://auth.modernization.internal",
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_create_job_success(mock_session: AsyncMock) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)

    job = await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/legacy",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python", "framework": "fastapi"},
        budget={"max_cost_cents": 50000},
        correlation_id="corr-123",
    )

    assert job.status == JobLifecycleState.QUEUED.value
    assert job.version == 1
    assert job.owner == str(principal.user_id)
    assert job.owner_user_id == principal.user_id
    assert job.tenant_id == principal.tenant_id
    assert job.current_stage == "queued"
    assert job.source_ref == "https://github.com/acme/legacy@v1.0.0"

    # Verify session additions: Job and JobMember and AuditEvent
    assert mock_session.add.call_count >= 2
    mock_session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_create_job_idempotency_returns_cached_job(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)

    idempotency_key = "idemp-key-create-001"
    existing_job_id = uuid.uuid4()
    existing_job = Job(
        id=existing_job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="queued",
        version=1,
        source_ref="https://github.com/acme/legacy@v1",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 10000},
    )

    payload = {
        "source_repository": "https://github.com/acme/legacy",
        "source_revision": "v1.0.0",
        "target_stack": {"language": "python"},
        "budget": {"max_cost_cents": 10000},
    }
    req_hash = compute_request_hash(payload)

    # Mock IdempotencyRepository to simulate existing record
    mock_record = MagicMock()
    mock_record.request_hash = req_hash
    mock_record.resource_id = existing_job_id
    monkeypatch.setattr(service._idempotency, "get_record", AsyncMock(return_value=mock_record))
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=existing_job))

    result_job = await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/legacy",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 10000},
        idempotency_key=idempotency_key,
    )

    assert result_job is existing_job
    # No new job added
    assert mock_session.add.call_count == 0


@pytest.mark.asyncio
async def test_create_job_idempotency_conflict_on_different_payload(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)

    idempotency_key = "idemp-key-conflict-001"
    mock_record = MagicMock()
    mock_record.request_hash = "different_hash_value"
    monkeypatch.setattr(service._idempotency, "get_record", AsyncMock(return_value=mock_record))

    with pytest.raises(IdempotencyConflictError):
        await service.create_job(
            principal=principal,
            source_repository="https://github.com/acme/legacy",
            source_revision="v1.0.0",
            target_stack_spec={"language": "python"},
            budget={"max_cost_cents": 10000},
            idempotency_key=idempotency_key,
        )


@pytest.mark.asyncio
async def test_get_job_success_and_not_found(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="queued",
        version=1,
        source_ref="https://example.com/repo@main",
        target_stack_spec={},
        budget={},
    )

    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))
    found = await service.get_job(principal, job_id)
    assert found is job

    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=None))
    with pytest.raises(JobNotFoundError):
        await service.get_job(principal, uuid.uuid4())


@pytest.mark.asyncio
async def test_get_job_status_formatting(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="awaiting_approval",
        version=3,
        current_stage="architecture",
        source_ref="https://example.com/repo@main",
        target_stack_spec={},
        budget={},
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))

    status_resp = await service.get_job_status(principal=principal, job_id=job_id)
    assert status_resp.job_id == job_id
    assert status_resp.status == JobStatus.AWAITING_APPROVAL
    assert status_resp.version == 3
    assert status_resp.needs_human is True
    assert status_resp.current_stage == "architecture"


@pytest.mark.asyncio
async def test_pause_job_increments_version(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="running",
        version=1,
        source_ref="https://example.com/repo@main",
        target_stack_spec={},
        budget={},
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))

    paused_job = await service.pause_job(
        principal=principal,
        job_id=job_id,
        expected_version=1,
        reason="Manual investigation required",
    )

    assert paused_job.status == JobLifecycleState.PAUSED.value
    assert paused_job.version == 2
    assert paused_job.paused_at is not None


@pytest.mark.asyncio
async def test_pause_job_stale_version_raises_conflict(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="running",
        version=3,  # Current is 3
        source_ref="https://example.com/repo@main",
        target_stack_spec={},
        budget={},
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))

    with pytest.raises(JobConcurrencyConflictError, match="expected 1, but actual version is 3"):
        await service.pause_job(
            principal=principal,
            job_id=job_id,
            expected_version=1,  # Stale expected version
        )


@pytest.mark.asyncio
async def test_resume_job_from_paused(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="paused",
        version=2,
        source_ref="https://example.com/repo@main",
        target_stack_spec={},
        budget={},
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))

    resumed_job = await service.resume_job(
        principal=principal,
        job_id=job_id,
        expected_version=2,
        reason="Investigation resolved",
    )

    assert resumed_job.status == JobLifecycleState.RUNNING.value
    assert resumed_job.version == 3
    assert resumed_job.started_at is not None


@pytest.mark.asyncio
async def test_cancel_job_sets_terminal_timestamps(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="running",
        version=2,
        source_ref="https://example.com/repo@main",
        target_stack_spec={},
        budget={},
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))

    cancelled_job = await service.cancel_job(
        principal=principal,
        job_id=job_id,
        expected_version=2,
        reason="Budget exhausted or user requested abort",
    )

    assert cancelled_job.status == JobLifecycleState.CANCELLED.value
    assert cancelled_job.version == 3
    assert cancelled_job.cancelled_at is not None
    assert cancelled_job.finished_at is not None


@pytest.mark.asyncio
async def test_terminal_job_cannot_be_paused_or_resumed(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="cancelled",
        version=3,
        source_ref="https://example.com/repo@main",
        target_stack_spec={},
        budget={},
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))

    with pytest.raises(TerminalJobMutationError):
        await service.pause_job(principal=principal, job_id=job_id, expected_version=3)

    with pytest.raises(TerminalJobMutationError):
        await service.resume_job(principal=principal, job_id=job_id, expected_version=3)


@pytest.mark.asyncio
async def test_transition_job_with_transient_failure_and_recovery(
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = JobService(mock_session)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="running",
        version=1,
        source_ref="https://example.com/repo@main",
        target_stack_spec={},
        budget={},
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))

    # 1. Transition to FAILED with transient failure
    failed_job = await service.transition_job(
        principal=principal,
        job_id=job_id,
        target_state=JobLifecycleState.FAILED,
        expected_version=1,
        failure_classification=FailureClassification.TRANSIENT,
        failure_reason="Temporary rate limit timeout",
    )
    assert failed_job.status == JobLifecycleState.FAILED.value
    assert failed_job.version == 2
    assert failed_job.failure_classification == "transient"

    # 2. Transition back to RUNNING
    recovered_job = await service.transition_job(
        principal=principal,
        job_id=job_id,
        target_state=JobLifecycleState.RUNNING,
        expected_version=2,
        failure_classification=FailureClassification.TRANSIENT,
    )
    assert recovered_job.status == JobLifecycleState.RUNNING.value
    assert recovered_job.version == 3
