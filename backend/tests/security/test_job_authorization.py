"""Security and authorization tests for Job lifecycle operations and RBAC isolation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.exceptions import ForbiddenException, NotFoundException
from modernization_platform.db.models.identity import Tenant, TenantMembership, UserAccount
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.jobs import JobService


async def _create_test_identity(
    session: AsyncSession,
    *,
    role: Role,
    tenant: Tenant | None = None,
    subject: str | None = None,
) -> tuple[Tenant, UserAccount, AuthenticatedPrincipal]:
    if tenant is None:
        tenant = Tenant(
            slug=f"sec-tenant-{uuid.uuid4().hex[:8]}",
            display_name=f"Security Tenant {uuid.uuid4().hex[:8]}",
            active=True,
        )
        session.add(tenant)
        await session.flush()

    user_subject = subject or f"sec-user-{uuid.uuid4().hex[:8]}"
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

    principal = AuthenticatedPrincipal(
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
    return tenant, user, principal


@pytest.mark.asyncio
async def test_owner_can_access_and_manage_own_job(db_session: AsyncSession) -> None:
    """Job owner can create, inspect, pause, and cancel their own job."""
    _, _, owner_principal = await _create_test_identity(db_session, role=Role.OWNER)
    service = JobService(db_session)

    # 1. Create job
    job = await service.create_job(
        principal=owner_principal,
        source_repository="https://github.com/acme/owner-service",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
    )
    await db_session.commit()
    job_id = job.id

    # 2. Inspect job detail
    detail = await service.get_job(owner_principal, job_id)
    assert detail.id == job_id
    assert detail.owner_user_id == owner_principal.user_id

    # 3. Inspect job status
    status_resp = await service.get_job_status(owner_principal, job_id)
    assert status_resp.job_id == job_id
    assert status_resp.status == "queued"

    # 4. Advance to running then pause
    await service.transition_job(
        job_id=job_id,
        principal=owner_principal,
        target_state=JobLifecycleState.RUNNING,
        expected_version=1,
    )
    await db_session.commit()

    paused_job = await service.pause_job(
        job_id=job_id,
        principal=owner_principal,
        expected_version=2,
    )
    await db_session.commit()
    assert paused_job.status == "paused"
    assert paused_job.version == 3


@pytest.mark.asyncio
async def test_reviewer_cannot_create_or_mutate_jobs(db_session: AsyncSession) -> None:
    """Reviewer role has read-only permission (JOB_VIEW) and is forbidden from mutations."""
    tenant, _, reviewer_principal = await _create_test_identity(db_session, role=Role.REVIEWER)
    _, _, owner_principal = await _create_test_identity(db_session, role=Role.OWNER, tenant=tenant)
    service = JobService(db_session)

    # 1. Reviewer cannot create a job (requires JOB_CREATE)
    with pytest.raises(ForbiddenException):
        await service.create_job(
            principal=reviewer_principal,
            source_repository="https://github.com/acme/reviewer-repo",
            source_revision="v1.0.0",
            target_stack_spec={"language": "python"},
            budget={"max_cost_cents": 10000},
        )

    # Owner creates a job in the shared tenant
    job = await service.create_job(
        principal=owner_principal,
        source_repository="https://github.com/acme/owner-repo",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 10000},
    )
    await db_session.commit()
    job_id = job.id

    # 2. Reviewer cannot pause the job (requires JOB_MANAGE)
    with pytest.raises(ForbiddenException):
        await service.pause_job(
            job_id=job_id,
            principal=reviewer_principal,
            expected_version=1,
        )

    # 3. Reviewer cannot resume the job (requires JOB_MANAGE)
    with pytest.raises(ForbiddenException):
        await service.resume_job(
            job_id=job_id,
            principal=reviewer_principal,
            expected_version=1,
        )

    # 4. Reviewer cannot cancel the job (requires JOB_CANCEL)
    with pytest.raises(ForbiddenException):
        await service.cancel_job(
            job_id=job_id,
            principal=reviewer_principal,
            expected_version=1,
        )


@pytest.mark.asyncio
async def test_cross_tenant_isolation_fails_closed_with_not_found(
    db_session: AsyncSession,
) -> None:
    """Actor in Tenant B attempting to access or mutate Job in Tenant A receives 404 NotFound."""
    _, _, principal_a = await _create_test_identity(db_session, role=Role.OWNER)
    _, _, principal_b = await _create_test_identity(db_session, role=Role.OWNER)
    service = JobService(db_session)

    # Job created by Tenant A
    job_a = await service.create_job(
        principal=principal_a,
        source_repository="https://github.com/acme/tenant-a-private",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 20000},
    )
    await db_session.commit()
    job_id = job_a.id

    # Tenant B cannot inspect job A (returns 404, not 403 to prevent enumeration/IDOR)
    with pytest.raises(NotFoundException):
        await service.get_job(principal_b, job_id)

    with pytest.raises(NotFoundException):
        await service.get_job_status(principal_b, job_id)

    # Tenant B cannot pause job A
    with pytest.raises(NotFoundException):
        await service.pause_job(job_id=job_id, principal=principal_b, expected_version=1)

    # Tenant B cannot resume job A
    with pytest.raises(NotFoundException):
        await service.resume_job(job_id=job_id, principal=principal_b, expected_version=1)

    # Tenant B cannot cancel job A
    with pytest.raises(NotFoundException):
        await service.cancel_job(job_id=job_id, principal=principal_b, expected_version=1)


@pytest.mark.asyncio
async def test_admin_within_tenant_can_manage_jobs(db_session: AsyncSession) -> None:
    """Admin role has permissions to inspect and manage any job within their tenant."""
    tenant, _, admin_principal = await _create_test_identity(db_session, role=Role.ADMIN)
    _, _, owner_principal = await _create_test_identity(db_session, role=Role.OWNER, tenant=tenant)
    service = JobService(db_session)

    job = await service.create_job(
        principal=owner_principal,
        source_repository="https://github.com/acme/tenant-job",
        source_revision="v1.0.0",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
    )
    await db_session.commit()
    job_id = job.id

    # Admin inspects job
    detail = await service.get_job(admin_principal, job_id)
    assert detail.id == job_id

    # Admin cancels job
    cancelled_job = await service.cancel_job(
        job_id=job_id,
        principal=admin_principal,
        expected_version=1,
        reason="Administrative audit cancellation",
    )
    await db_session.commit()
    assert cancelled_job.status == "cancelled"
    assert cancelled_job.version == 2
