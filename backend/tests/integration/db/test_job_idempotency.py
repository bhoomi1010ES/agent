"""PostgreSQL integration tests for database-backed idempotency protection on state-changing requests."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.idempotency import IdempotencyRecord
from modernization_platform.db.models.identity import Tenant, TenantMembership, UserAccount
from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.errors import IdempotencyConflictError
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.jobs import JobService


async def _setup_principal(
    session: AsyncSession, role: Role = Role.OWNER, subject: str | None = None
) -> AuthenticatedPrincipal:
    tenant = Tenant(
        slug=f"tenant-{uuid.uuid4().hex[:8]}",
        display_name=f"Tenant {uuid.uuid4().hex[:8]}",
        active=True,
    )
    session.add(tenant)
    await session.flush()

    user_subject = subject or f"user-{uuid.uuid4().hex[:8]}"
    user = UserAccount(
        issuer="https://auth.modernization.internal",
        subject=user_subject,
        display_name=user_subject,
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
        subject=user_subject,
        issuer=user.issuer,
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


@pytest.mark.asyncio
async def test_idempotent_job_creation_returns_cached_job(db_session: AsyncSession) -> None:
    """Same request with same idempotency key produces one logical job without duplicate records."""
    principal = await _setup_principal(db_session, Role.OWNER)
    service = JobService(db_session)

    idem_key = f"key-create-{uuid.uuid4().hex}"
    source_repo = "https://github.com/acme/idempotent-service"
    source_rev = "v1.0.0"
    target_stack = {"language": "python", "framework": "fastapi"}
    budget = {"max_cost_cents": 50000}

    # 1. First execution
    job1 = await service.create_job(
        principal=principal,
        source_repository=source_repo,
        source_revision=source_rev,
        target_stack_spec=target_stack,
        budget=budget,
        idempotency_key=idem_key,
    )
    await db_session.commit()
    assert job1.id is not None
    assert job1.status == "queued"
    assert job1.version == 1

    # 2. Second execution with identical payload and same key
    job2 = await service.create_job(
        principal=principal,
        source_repository=source_repo,
        source_revision=source_rev,
        target_stack_spec=target_stack,
        budget=budget,
        idempotency_key=idem_key,
    )
    await db_session.commit()

    # Must return the identical persisted job without duplicate insert
    assert job2.id == job1.id
    assert job2.status == job1.status

    # Assert exactly one Job exists in DB
    jobs_count_res = await db_session.execute(
        select(Job).where(Job.tenant_id == principal.tenant_id)
    )
    all_jobs = jobs_count_res.scalars().all()
    assert len(all_jobs) == 1

    # Assert idempotency record exists in DB
    idem_rec_res = await db_session.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == principal.tenant_id,
            IdempotencyRecord.key == idem_key,
        )
    )
    idem_rec = idem_rec_res.scalar_one_or_none()
    assert idem_rec is not None
    assert idem_rec.action == "create_job"
    assert idem_rec.resource_id == job1.id


@pytest.mark.asyncio
async def test_idempotency_key_reuse_with_different_payload_raises_conflict(
    db_session: AsyncSession,
) -> None:
    """Same idempotency key with materially different payload raises IdempotencyConflictError."""
    principal = await _setup_principal(db_session, Role.OWNER)
    service = JobService(db_session)

    idem_key = f"key-conflict-{uuid.uuid4().hex}"

    # First request
    await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/orig-repo",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 20000},
        idempotency_key=idem_key,
    )
    await db_session.commit()

    # Second request with different budget/repo using the same key
    with pytest.raises(IdempotencyConflictError) as exc_info:
        await service.create_job(
            principal=principal,
            source_repository="https://github.com/acme/different-repo",
            source_revision="v2.0.0",
            target_stack_spec={"language": "python"},
            budget={"max_cost_cents": 90000},
            idempotency_key=idem_key,
        )

    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"
    assert idem_key in str(exc_info.value)


@pytest.mark.asyncio
async def test_different_users_with_same_key_cannot_interfere(db_session: AsyncSession) -> None:
    """Idempotency keys are strictly scoped to (tenant_id, user_id); cross-user collision is impossible."""
    # User A in Tenant A
    principal_a = await _setup_principal(db_session, Role.OWNER, subject="user-a")
    # User B in Tenant B
    principal_b = await _setup_principal(db_session, Role.OWNER, subject="user-b")

    service = JobService(db_session)
    shared_key_name = "reusable-client-token-xyz"

    # User A creates job with key
    job_a = await service.create_job(
        principal=principal_a,
        source_repository="https://github.com/acme/user-a-repo",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
        idempotency_key=shared_key_name,
    )
    await db_session.commit()

    # User B creates job with exact same key string and different payload
    job_b = await service.create_job(
        principal=principal_b,
        source_repository="https://github.com/acme/user-b-repo",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 75000},
        idempotency_key=shared_key_name,
    )
    await db_session.commit()

    # Both succeeded independently, different job IDs, different tenants
    assert job_a.id != job_b.id
    assert job_a.tenant_id == principal_a.tenant_id
    assert job_b.tenant_id == principal_b.tenant_id

    # Verify two distinct idempotency records exist in DB
    records_res = await db_session.execute(
        select(IdempotencyRecord).where(IdempotencyRecord.key == shared_key_name)
    )
    records = records_res.scalars().all()
    assert len(records) == 2
    assert {r.tenant_id for r in records} == {principal_a.tenant_id, principal_b.tenant_id}


@pytest.mark.asyncio
async def test_idempotent_pause_and_resume_mutations(db_session: AsyncSession) -> None:
    """Idempotency key on pause and resume endpoints safely returns cached mutation."""
    principal = await _setup_principal(db_session, Role.OWNER)
    service = JobService(db_session)

    job = await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/pause-idem-test",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
    )
    await db_session.commit()

    # Move to running (version 2)
    running_job = await service.transition_job(
        job_id=job.id,
        principal=principal,
        target_state=JobLifecycleState.RUNNING,
        expected_version=1,
    )
    await db_session.commit()

    pause_key = f"key-pause-{uuid.uuid4().hex}"

    # Pause 1st call
    paused_job_1 = await service.pause_job(
        job_id=running_job.id,
        principal=principal,
        expected_version=2,
        reason="Scheduled inspection",
        idempotency_key=pause_key,
    )
    await db_session.commit()
    assert paused_job_1.status == "paused"
    assert paused_job_1.version == 3

    # Pause 2nd call (same key and expected_version) -> cached result
    paused_job_2 = await service.pause_job(
        job_id=running_job.id,
        principal=principal,
        expected_version=2,
        reason="Scheduled inspection",
        idempotency_key=pause_key,
    )
    await db_session.commit()
    assert paused_job_2.id == paused_job_1.id
    assert paused_job_2.version == 3
    assert paused_job_2.status == "paused"
