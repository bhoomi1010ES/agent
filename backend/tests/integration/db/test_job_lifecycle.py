"""PostgreSQL integration tests for Job lifecycle states, transitions, timestamps, and audit consistency."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.audit_event import AuditEvent
from modernization_platform.db.models.identity import Tenant, TenantMembership, UserAccount
from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.errors import (
    JobCompletionBlockedError,
    TerminalJobMutationError,
)
from modernization_platform.domain.jobs.states import FailureClassification, JobLifecycleState
from modernization_platform.domain.jobs.transitions import CompletionGuard
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.jobs import JobService


async def _setup_principal(
    session: AsyncSession, role: Role = Role.OWNER, subject: str = "lifecycle-architect"
) -> AuthenticatedPrincipal:
    tenant = Tenant(
        slug=f"tenant-{uuid.uuid4().hex[:8]}",
        display_name=f"Tenant {uuid.uuid4().hex[:8]}",
        active=True,
    )
    session.add(tenant)
    await session.flush()

    user = UserAccount(
        issuer="https://auth.modernization.internal",
        subject=subject,
        display_name=subject,
        active=True,
    )
    session.add(user)
    await session.flush()

    membership = TenantMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        role=role.value,
        active=True,
    )
    session.add(membership)
    await session.flush()

    return AuthenticatedPrincipal(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership.id,
        session_id=uuid.uuid4(),
        subject=subject,
        issuer=user.issuer,
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


@pytest.mark.asyncio
async def test_full_job_lifecycle_progression(db_session: AsyncSession) -> None:
    """Verify state transitions: queued -> running -> paused -> running -> completed."""
    principal = await _setup_principal(db_session, Role.OWNER)
    service = JobService(db_session)

    # 1. Create job (initial: queued, version: 1)
    create_resp = await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/legacy-crm",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python", "framework": "fastapi"},
        budget={"max_cost_cents": 50000},
    )
    await db_session.commit()
    job_id = create_resp.id
    assert create_resp.status == "queued"
    assert create_resp.version == 1

    # Verify audit event for creation
    audit_res = await db_session.execute(
        select(AuditEvent).where(AuditEvent.job_id == job_id, AuditEvent.action == "JOB_CREATED")
    )
    create_audit = audit_res.scalar_one_or_none()
    assert create_audit is not None

    # 2. Transition queued -> running (version: 2)
    running_resp = await service.transition_job(
        job_id=job_id,
        principal=principal,
        target_state=JobLifecycleState.RUNNING,
        expected_version=1,
        current_stage="discovery",
        reason="Agent worker started discovery",
    )
    await db_session.commit()
    assert running_resp.status == "running"
    assert running_resp.version == 2

    # Check timestamps and audit in DB
    job_in_db = await db_session.get(Job, job_id)
    assert job_in_db is not None
    assert job_in_db.status == "running"
    assert job_in_db.version == 2
    assert job_in_db.started_at is not None
    assert job_in_db.current_stage == "discovery"

    # 3. Transition running -> paused (version: 3)
    pause_resp = await service.pause_job(
        job_id=job_id,
        principal=principal,
        expected_version=2,
        reason="Operator manual pause",
    )
    await db_session.commit()
    assert pause_resp.status == "paused"
    assert pause_resp.version == 3

    job_in_db = await db_session.get(Job, job_id)
    assert job_in_db is not None
    assert job_in_db.status == "paused"
    assert job_in_db.version == 3
    assert job_in_db.paused_at is not None

    # 4. Transition paused -> running (resume) (version: 4)
    resume_resp = await service.resume_job(
        job_id=job_id,
        principal=principal,
        expected_version=3,
        reason="Operator resumed execution",
    )
    await db_session.commit()
    assert resume_resp.status == "running"
    assert resume_resp.version == 4

    # 5. Attempt completion when stages incomplete -> blocked
    with pytest.raises(JobCompletionBlockedError):
        await service.transition_job(
            job_id=job_id,
            principal=principal,
            target_state=JobLifecycleState.COMPLETED,
            expected_version=4,
            current_stage="verification",
            completed_stages=["discovery", "blueprint"],  # missing generation, verification
        )

    # 6. Complete when all required stages are done (version: 5)
    all_stages = list(CompletionGuard.DEFAULT_REQUIRED_STAGES)
    complete_resp = await service.transition_job(
        job_id=job_id,
        principal=principal,
        target_state=JobLifecycleState.COMPLETED,
        expected_version=4,
        current_stage="verification",
        completed_stages=all_stages,
        has_pending_gates=False,
    )
    await db_session.commit()
    assert complete_resp.status == "completed"
    assert complete_resp.version == 5

    job_in_db = await db_session.get(Job, job_id)
    assert job_in_db is not None
    assert job_in_db.status == "completed"
    assert job_in_db.completed_at is not None
    assert job_in_db.finished_at is not None


@pytest.mark.asyncio
async def test_cancellation_and_terminal_immutability(db_session: AsyncSession) -> None:
    """Verify cancellation transition and that terminal states cannot be mutated."""
    principal = await _setup_principal(db_session, Role.OWNER)
    service = JobService(db_session)

    create_resp = await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/legacy-billing",
        source_revision="v2.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 25000},
    )
    await db_session.commit()
    job_id = create_resp.id

    # Cancel from queued
    cancel_resp = await service.cancel_job(
        job_id=job_id,
        principal=principal,
        expected_version=1,
        reason="Budget reallocation",
    )
    await db_session.commit()
    assert cancel_resp.status == "cancelled"
    assert cancel_resp.version == 2

    job_in_db = await db_session.get(Job, job_id)
    assert job_in_db is not None
    assert job_in_db.status == "cancelled"
    assert job_in_db.cancelled_at is not None

    # Any mutation on terminal job must raise TerminalJobMutationError
    with pytest.raises(TerminalJobMutationError):
        await service.pause_job(job_id=job_id, principal=principal, expected_version=2)

    with pytest.raises(TerminalJobMutationError):
        await service.resume_job(job_id=job_id, principal=principal, expected_version=2)

    with pytest.raises(TerminalJobMutationError):
        await service.cancel_job(job_id=job_id, principal=principal, expected_version=2)


@pytest.mark.asyncio
async def test_failure_classification_semantics(db_session: AsyncSession) -> None:
    """Verify recording of transient vs terminal failure classifications."""
    principal = await _setup_principal(db_session, Role.OWNER)
    service = JobService(db_session)

    create_resp = await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/legacy-erp",
        source_revision="v3.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 10000},
    )
    await db_session.commit()
    job_id = create_resp.id

    # Move to running
    await service.transition_job(
        job_id=job_id,
        principal=principal,
        target_state=JobLifecycleState.RUNNING,
        expected_version=1,
    )
    await db_session.commit()

    # Move to failed with terminal failure classification
    fail_resp = await service.transition_job(
        job_id=job_id,
        principal=principal,
        target_state=JobLifecycleState.FAILED,
        expected_version=2,
        reason="Unrecoverable AST syntax parsing failure",
        failure_classification=FailureClassification.TERMINAL,
    )
    await db_session.commit()
    assert fail_resp.status == "failed"
    assert fail_resp.version == 3

    job_in_db = await db_session.get(Job, job_id)
    assert job_in_db is not None
    assert job_in_db.status == "failed"
    assert job_in_db.failure_classification == "terminal"
    assert job_in_db.failure_reason == "Unrecoverable AST syntax parsing failure"
    assert job_in_db.failed_at is not None


@pytest.mark.asyncio
async def test_transactional_rollback_when_audit_fails(db_session: AsyncSession) -> None:
    """Verify that if audit recording fails, job mutation is completely rolled back."""
    principal = await _setup_principal(db_session, Role.OWNER)
    service = JobService(db_session)

    create_resp = await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/legacy-trans",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 10000},
    )
    await db_session.commit()
    job_id = create_resp.id

    # Move to running first (version 2)
    await service.transition_job(
        job_id=job_id,
        principal=principal,
        target_state=JobLifecycleState.RUNNING,
        expected_version=1,
    )
    await db_session.commit()

    # Force audit failure during pause
    with patch.object(
        service._audit,
        "append_event",
        side_effect=RuntimeError("Simulated database failure during audit insert"),
    ):
        with pytest.raises(RuntimeError, match="Simulated database failure"):
            await service.pause_job(
                job_id=job_id,
                principal=principal,
                expected_version=2,
            )
        await db_session.rollback()

    # Verify job remained running at version 2, paused_at was rolled back
    job_in_db = await db_session.get(Job, job_id)
    assert job_in_db is not None
    assert job_in_db.status == "running"
    assert job_in_db.version == 2
    assert job_in_db.paused_at is None
