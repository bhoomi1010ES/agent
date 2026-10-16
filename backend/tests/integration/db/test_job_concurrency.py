"""PostgreSQL integration tests for Job optimistic concurrency, version increments, and conflict prevention."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from modernization_platform.db.models.identity import Tenant, TenantMembership, UserAccount
from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.errors import JobConcurrencyConflictError
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
async def test_stale_expected_version_raises_concurrency_conflict(db_session: AsyncSession) -> None:
    """An update specifying a stale expected version must be rejected without overwriting state."""
    principal = await _setup_principal(db_session, Role.OWNER)
    service = JobService(db_session)

    # 1. Create job (version: 1, queued)
    job = await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/legacy-concurrency",
        source_revision="v1.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
    )
    await db_session.commit()
    job_id = job.id
    assert job.version == 1

    # 2. Advance to running (version becomes 2)
    running_job = await service.transition_job(
        job_id=job_id,
        principal=principal,
        target_state=JobLifecycleState.RUNNING,
        expected_version=1,
    )
    await db_session.commit()
    assert running_job.version == 2

    # 3. Attempt to pause with stale expected_version=1 -> raises JobConcurrencyConflictError
    with pytest.raises(JobConcurrencyConflictError) as exc_info:
        await service.pause_job(
            job_id=job_id,
            principal=principal,
            expected_version=1,  # Stale: actual version is 2
        )

    assert "Stale job version" in str(exc_info.value)
    assert exc_info.value.code == "CONCURRENCY_CONFLICT"

    # State in database remains untouched (still running at version 2)
    job_in_db = await db_session.get(Job, job_id)
    assert job_in_db is not None
    assert job_in_db.status == "running"
    assert job_in_db.version == 2


@pytest.mark.asyncio
async def test_monotonic_version_progression(db_session: AsyncSession) -> None:
    """Verify that version increases monotonically: 1 -> 2 -> 3 -> 4."""
    principal = await _setup_principal(db_session, Role.OWNER)
    service = JobService(db_session)

    job = await service.create_job(
        principal=principal,
        source_repository="https://github.com/acme/monotonic-repo",
        source_revision="v1.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
    )
    await db_session.commit()
    job_id = job.id
    assert job.version == 1

    # Transition 1: queued -> running (v1 -> v2)
    j2 = await service.transition_job(
        job_id=job_id,
        principal=principal,
        target_state=JobLifecycleState.RUNNING,
        expected_version=1,
    )
    await db_session.commit()
    assert j2.version == 2

    # Transition 2: running -> paused (v2 -> v3)
    j3 = await service.pause_job(
        job_id=job_id,
        principal=principal,
        expected_version=2,
    )
    await db_session.commit()
    assert j3.version == 3

    # Transition 3: paused -> running (v3 -> v4)
    j4 = await service.resume_job(
        job_id=job_id,
        principal=principal,
        expected_version=3,
    )
    await db_session.commit()
    assert j4.version == 4


@pytest.mark.asyncio
async def test_simultaneous_concurrent_updates_prevent_silent_overwrites(
    db_engine: AsyncEngine,
) -> None:
    """Two concurrent updates with identical expected version: exactly one succeeds, other fails."""
    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # 1. Setup tenant, user, principal and a running job in setup session
    async with session_factory() as setup_session:
        principal = await _setup_principal(setup_session, Role.OWNER)
        service = JobService(setup_session)
        job = await service.create_job(
            principal=principal,
            source_repository="https://github.com/acme/race-condition-test",
            source_revision="v1.0",
            target_stack_spec={"language": "python"},
            budget={"max_cost_cents": 50000},
        )
        await setup_session.flush()

        running_job = await service.transition_job(
            job_id=job.id,
            principal=principal,
            target_state=JobLifecycleState.RUNNING,
            expected_version=1,
        )
        await setup_session.commit()
        job_id = running_job.id
        current_version = running_job.version
        assert current_version == 2

    # 2. Concurrently attempt two conflicting operations with expected_version=2
    # One attempts pause, other attempts cancel
    results: list[str] = []
    errors: list[Exception] = []

    async def attempt_pause() -> None:
        async with session_factory() as session:
            try:
                svc = JobService(session)
                await svc.pause_job(
                    job_id=job_id,
                    principal=principal,
                    expected_version=current_version,
                )
                await session.commit()
                results.append("pause")
            except Exception as e:
                await session.rollback()
                errors.append(e)

    async def attempt_cancel() -> None:
        async with session_factory() as session:
            try:
                svc = JobService(session)
                await svc.cancel_job(
                    job_id=job_id,
                    principal=principal,
                    expected_version=current_version,
                )
                await session.commit()
                results.append("cancel")
            except Exception as e:
                await session.rollback()
                errors.append(e)

    await asyncio.gather(attempt_pause(), attempt_cancel(), return_exceptions=True)

    # Exactly one must succeed, and the other must raise JobConcurrencyConflictError
    assert len(results) == 1, f"Expected 1 success, got {results}"
    assert len(errors) == 1, f"Expected 1 error, got {errors}"
    assert isinstance(errors[0], JobConcurrencyConflictError)

    # Final DB state reflects the single winning transaction, version incremented to 3
    async with session_factory() as verify_session:
        final_job = await verify_session.get(Job, job_id)
        assert final_job is not None
        assert final_job.version == 3
        assert final_job.status in ("paused", "cancelled")
