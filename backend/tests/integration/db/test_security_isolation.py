"""PostgreSQL security tests for tenant, resource, gate, and worker isolation."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.app import create_app
from modernization_platform.config.settings import Settings
from modernization_platform.core.exceptions import ForbiddenException, NotFoundException
from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.audit_event import AuditEvent
from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.identity import (
    AuthSession,
    JobMember,
    Tenant,
    TenantMembership,
    UserAccount,
)
from modernization_platform.db.models.job import Job
from modernization_platform.db.session import get_db_session
from modernization_platform.repositories.identities import hash_token_id
from modernization_platform.security.permissions import Permission, Role
from modernization_platform.security.principals import (
    AuthenticatedPrincipal,
    WorkerAuthorizationContext,
)
from modernization_platform.services.authorization import AuthorizationService
from tests.security.jwt_helpers import generate_key_pair, issue_token


async def _create_identity(
    session: AsyncSession,
    *,
    tenant: Tenant,
    role: Role,
    subject: str,
) -> tuple[UserAccount, TenantMembership, AuthenticatedPrincipal]:
    user = UserAccount(
        issuer="https://identity.test",
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
    principal = AuthenticatedPrincipal(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership.id,
        session_id=uuid.uuid4(),
        subject=subject,
        issuer=user.issuer,
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        authentication_method="oidc_jwt",
    )
    return user, membership, principal


async def _create_job(
    session: AsyncSession,
    *,
    tenant: Tenant,
    owner: UserAccount,
    suffix: str,
) -> Job:
    job = Job(
        owner=str(owner.id),
        tenant_id=tenant.id,
        owner_user_id=owner.id,
        source_ref=f"https://example.invalid/{suffix}.git",
        status="pending",
    )
    session.add(job)
    await session.flush()
    return job


@pytest.mark.asyncio
async def test_job_and_artifact_access_is_owner_member_or_tenant_admin_only(
    db_session: AsyncSession,
) -> None:
    tenant_a = Tenant(slug="tenant-a", display_name="Tenant A", active=True)
    tenant_b = Tenant(slug="tenant-b", display_name="Tenant B", active=True)
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    owner_a, _owner_membership, owner_principal = await _create_identity(
        db_session, tenant=tenant_a, role=Role.OWNER, subject="owner-a"
    )
    owner_b, _other_membership, other_owner = await _create_identity(
        db_session, tenant=tenant_a, role=Role.OWNER, subject="owner-b"
    )
    _reviewer, reviewer_membership, reviewer = await _create_identity(
        db_session, tenant=tenant_a, role=Role.REVIEWER, subject="reviewer-a"
    )
    _admin, _admin_membership, admin = await _create_identity(
        db_session, tenant=tenant_a, role=Role.ADMIN, subject="admin-a"
    )
    _foreign_admin, _foreign_membership, foreign_admin = await _create_identity(
        db_session, tenant=tenant_b, role=Role.ADMIN, subject="admin-b"
    )

    job_a = await _create_job(db_session, tenant=tenant_a, owner=owner_a, suffix="job-a")
    job_b = await _create_job(db_session, tenant=tenant_a, owner=owner_b, suffix="job-b")
    db_session.add(JobMember(job_id=job_a.id, membership_id=reviewer_membership.id))
    artifact_a = Artifact(
        job_id=job_a.id,
        type="RepoInventory",
        version=1,
        content_hash="a" * 64,
        storage_ref="sha256/aa/artifact-a",
    )
    artifact_b = Artifact(
        job_id=job_b.id,
        type="RepoInventory",
        version=1,
        content_hash="b" * 64,
        storage_ref="sha256/bb/artifact-b",
    )
    db_session.add_all([artifact_a, artifact_b])
    await db_session.flush()
    service = AuthorizationService(db_session)

    assert (await service.get_job(owner_principal, job_a.id)).id == job_a.id
    assert (await service.get_job(reviewer, job_a.id)).id == job_a.id
    assert (await service.get_job(admin, job_b.id)).id == job_b.id
    assert (await service.get_artifact(owner_principal, artifact_a.id)).id == artifact_a.id
    assert (await service.get_artifact(reviewer, artifact_a.id)).id == artifact_a.id

    with pytest.raises(NotFoundException):
        await service.get_job(owner_principal, job_b.id)
    with pytest.raises(NotFoundException):
        await service.get_artifact(other_owner, artifact_a.id)
    with pytest.raises(NotFoundException):
        await service.get_job(foreign_admin, job_a.id)
    with pytest.raises(NotFoundException):
        await service.get_artifact(foreign_admin, artifact_a.id)


@pytest.mark.asyncio
async def test_gate_decision_requires_approver_and_records_authenticated_actor(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(slug="gate-tenant", display_name="Gate Tenant", active=True)
    foreign_tenant = Tenant(slug="foreign-gate", display_name="Foreign Gate", active=True)
    db_session.add_all([tenant, foreign_tenant])
    await db_session.flush()
    owner, _owner_membership, owner_principal = await _create_identity(
        db_session, tenant=tenant, role=Role.OWNER, subject="gate-owner"
    )
    _reviewer, reviewer_membership, reviewer = await _create_identity(
        db_session, tenant=tenant, role=Role.REVIEWER, subject="gate-reviewer"
    )
    _admin_user, _admin_membership, admin = await _create_identity(
        db_session, tenant=tenant, role=Role.ADMIN, subject="gate-admin"
    )
    approver_user, approver_membership, approver = await _create_identity(
        db_session, tenant=tenant, role=Role.APPROVER, subject="gate-approver"
    )
    _foreign, foreign_membership, foreign_approver = await _create_identity(
        db_session,
        tenant=foreign_tenant,
        role=Role.APPROVER,
        subject="foreign-approver",
    )
    job = await _create_job(db_session, tenant=tenant, owner=owner, suffix="gate-job")
    db_session.add_all(
        [
            JobMember(job_id=job.id, membership_id=reviewer_membership.id),
            JobMember(job_id=job.id, membership_id=approver_membership.id),
        ]
    )
    gate = Gate(job_id=job.id, gate_type="G1_FEASIBILITY", state="pending")
    db_session.add(gate)
    await db_session.flush()
    service = AuthorizationService(db_session)

    with pytest.raises(ForbiddenException):
        await service.decide_gate(
            principal=owner_principal,
            job_id=job.id,
            gate_id=gate.id,
            decision="approved",
            feedback=None,
            waivers=[],
            correlation_id="owner-denied",
        )
    with pytest.raises(ForbiddenException):
        await service.decide_gate(
            principal=reviewer,
            job_id=job.id,
            gate_id=gate.id,
            decision="approved",
            feedback=None,
            waivers=[],
            correlation_id="reviewer-denied",
        )
    with pytest.raises(NotFoundException):
        await service.decide_gate(
            principal=foreign_approver,
            job_id=job.id,
            gate_id=gate.id,
            decision="approved",
            feedback=None,
            waivers=[],
            correlation_id="foreign-denied",
        )
    assert foreign_membership.tenant_id != tenant.id

    decision = await service.decide_gate(
        principal=approver,
        job_id=job.id,
        gate_id=gate.id,
        decision="approved",
        feedback="Evidence reviewed.",
        waivers=[],
        correlation_id="approved-request",
    )
    assert decision.actor == str(approver_user.id)
    assert decision.actor_user_id == approver_user.id
    assert gate.state == "approved"
    assert gate.resolved_at is not None

    audit = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.action == "GATE_DECIDED"))
    ).scalar_one()
    assert audit.actor_user_id == approver_user.id
    assert "token" not in audit.payload

    admin_gate = Gate(job_id=job.id, gate_type="G2_EQUIVALENCE", state="pending")
    db_session.add(admin_gate)
    await db_session.flush()
    admin_decision = await service.decide_gate(
        principal=admin,
        job_id=job.id,
        gate_id=admin_gate.id,
        decision="rejected",
        feedback="Admin review.",
        waivers=[],
        correlation_id="admin-approved-scope",
    )
    assert admin_decision.actor_user_id == admin.user_id


@pytest.mark.asyncio
async def test_background_context_revalidates_membership_and_job_scope(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(slug="worker-tenant", display_name="Worker Tenant", active=True)
    db_session.add(tenant)
    await db_session.flush()
    owner, membership, principal = await _create_identity(
        db_session, tenant=tenant, role=Role.OWNER, subject="worker-owner"
    )
    other, _other_membership, _other_principal = await _create_identity(
        db_session, tenant=tenant, role=Role.OWNER, subject="worker-other"
    )
    job = await _create_job(db_session, tenant=tenant, owner=owner, suffix="worker-job")
    other_job = await _create_job(db_session, tenant=tenant, owner=other, suffix="worker-other-job")
    service = AuthorizationService(db_session)

    context = await service.create_worker_context(principal, job.id)
    assert (await service.authorize_worker(context, Permission.JOB_VIEW)).id == job.id

    forged_context = WorkerAuthorizationContext(
        initiator_user_id=context.initiator_user_id,
        tenant_id=context.tenant_id,
        membership_id=context.membership_id,
        job_id=other_job.id,
        initiated_at=context.initiated_at,
    )
    with pytest.raises(NotFoundException):
        await service.authorize_worker(forged_context, Permission.JOB_VIEW)

    membership.active = False
    await db_session.flush()
    with pytest.raises(NotFoundException):
        await service.authorize_worker(context, Permission.JOB_VIEW)


@pytest.mark.asyncio
async def test_api_rejects_missing_unknown_revoked_and_forged_credentials(
    db_session: AsyncSession,
) -> None:
    keys = generate_key_pair()
    tenant = Tenant(slug="api-tenant", display_name="API Tenant", active=True)
    foreign_tenant = Tenant(slug="api-foreign", display_name="API Foreign", active=True)
    db_session.add_all([tenant, foreign_tenant])
    await db_session.flush()
    user, _membership, _principal = await _create_identity(
        db_session, tenant=tenant, role=Role.OWNER, subject="api-owner"
    )
    other_owner, _other_membership, _other_principal = await _create_identity(
        db_session,
        tenant=tenant,
        role=Role.OWNER,
        subject="api-other-owner",
    )
    secured_job = await _create_job(
        db_session,
        tenant=tenant,
        owner=user,
        suffix="api-secured-job",
    )
    secured_artifact = Artifact(
        job_id=secured_job.id,
        type="RepoInventory",
        version=1,
        content_hash="c" * 64,
        storage_ref="sha256/cc/api-artifact",
    )
    approver_user, approver_membership, _approver_principal = await _create_identity(
        db_session,
        tenant=tenant,
        role=Role.APPROVER,
        subject="api-approver",
    )
    gate = Gate(job_id=secured_job.id, gate_type="G1_FEASIBILITY", state="pending")
    db_session.add_all(
        [
            secured_artifact,
            gate,
            JobMember(job_id=secured_job.id, membership_id=approver_membership.id),
        ]
    )
    await db_session.flush()
    secured_job_id = secured_job.id
    secured_artifact_id = secured_artifact.id
    gate_id = gate.id
    other_job = await _create_job(
        db_session,
        tenant=tenant,
        owner=other_owner,
        suffix="api-other-job",
    )
    other_job_id = other_job.id
    token_id = "api-session"
    approver_token_id = "api-approver-session"
    token = issue_token(
        keys,
        tenant_id=tenant.id,
        subject=user.subject,
        token_id=token_id,
        overrides={"roles": ["admin"]},
    )
    unknown_token = issue_token(
        keys,
        tenant_id=tenant.id,
        subject=user.subject,
        token_id="unknown-session",
    )
    forged_tenant_token = issue_token(
        keys,
        tenant_id=foreign_tenant.id,
        subject=user.subject,
        token_id=token_id,
    )
    approver_token = issue_token(
        keys,
        tenant_id=tenant.id,
        subject=approver_user.subject,
        token_id=approver_token_id,
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    auth_session = AuthSession(
        token_id_hash=hash_token_id("https://identity.test", token_id),
        user_id=user.id,
        tenant_id=tenant.id,
        expires_at=expires_at,
        authentication_method="oidc_jwt",
    )
    db_session.add(auth_session)
    db_session.add(
        AuthSession(
            token_id_hash=hash_token_id("https://identity.test", approver_token_id),
            user_id=approver_user.id,
            tenant_id=tenant.id,
            expires_at=expires_at,
            authentication_method="oidc_jwt",
        )
    )
    await db_session.flush()

    settings = Settings(
        environment="test",
        debug=False,
        auth_jwt_issuer="https://identity.test",
        auth_jwt_audience="modernization-api",
        auth_jwt_public_key=SecretStr(keys.public_key),
        auth_clock_skew_seconds=0,
    )
    app = create_app(settings)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        missing = await client.get(f"/api/v1/jobs/{secured_job_id}")
        unauthenticated_job = await client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000")
        unauthenticated_artifact = await client.get(
            "/api/v1/artifacts/00000000-0000-0000-0000-000000000000"
        )
        unauthenticated_decision = await client.post(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000/gates/"
            "00000000-0000-0000-0000-000000000000/decisions",
            json={"decision": "approved"},
        )
        malformed = await client.get(
            f"/api/v1/jobs/{secured_job_id}", headers={"Authorization": "Bearer malformed"}
        )
        unknown = await client.get(
            f"/api/v1/jobs/{secured_job_id}",
            headers={"Authorization": f"Bearer {unknown_token}"},
        )
        forged_tenant = await client.get(
            f"/api/v1/jobs/{secured_job_id}",
            headers={"Authorization": f"Bearer {forged_tenant_token}"},
        )
        valid = await client.get(
            f"/api/v1/jobs/{secured_job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        forged_role_cross_owner = await client.get(
            f"/api/v1/jobs/{other_job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        secured_job_response = await client.get(
            f"/api/v1/jobs/{secured_job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        secured_artifact_response = await client.get(
            f"/api/v1/artifacts/{secured_artifact_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        gate_decision_response = await client.post(
            f"/api/v1/jobs/{secured_job_id}/gates/{gate_id}/decisions",
            headers={"Authorization": f"Bearer {approver_token}"},
            json={"decision": "approved", "feedback": "API approval"},
        )
        unauthorized_gate_decision = await client.post(
            f"/api/v1/jobs/{secured_job_id}/gates/{gate_id}/decisions",
            headers={"Authorization": f"Bearer {token}"},
            json={"decision": "rejected", "feedback": "Owner cannot decide."},
        )

        assert missing.status_code == 401
        assert unauthenticated_job.status_code == 401
        assert unauthenticated_artifact.status_code == 401
        assert unauthenticated_decision.status_code == 401
        assert malformed.status_code == 401
        assert unknown.status_code == 401
        assert forged_tenant.status_code == 401
        assert valid.status_code == 200
        assert forged_role_cross_owner.status_code == 404
        assert secured_job_response.status_code == 200
        assert secured_job_response.json()["job_id"] == str(secured_job_id)
        assert secured_artifact_response.status_code == 200
        assert secured_artifact_response.json()["artifact_id"] == str(secured_artifact_id)
        assert gate_decision_response.status_code == 200
        assert gate_decision_response.json()["decision"] == "approved"
        assert unauthorized_gate_decision.status_code == 403
        assert token not in valid.text

        auth_session.revoked_at = datetime.now(UTC)
        await db_session.flush()
        revoked = await client.get(
            f"/api/v1/jobs/{secured_job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoked.status_code == 401
