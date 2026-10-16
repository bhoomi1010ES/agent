"""Integration tests for reconciling LangGraph workflow state with PostgreSQL Job model."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.identity import (
    JobMember,
    Tenant,
    TenantMembership,
    UserAccount,
)
from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.workflows.engine import WorkflowEngine
from tests.integration.db.conftest import _PORT_AVAILABLE, _skip_or_fail_database


async def _create_test_principal(
    session: AsyncSession,
    role: Role = Role.OWNER,
) -> AuthenticatedPrincipal:
    tenant = Tenant(
        id=uuid.uuid4(),
        slug=f"test-tenant-{uuid.uuid4().hex[:8]}",
        display_name=f"Tenant {uuid.uuid4().hex[:8]}",
        active=True,
    )
    session.add(tenant)
    await session.flush()

    user = UserAccount(
        issuer="https://auth.modernization.internal",
        subject=f"user-{uuid.uuid4().hex[:8]}",
        display_name="Test User",
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
        subject=user.subject,
        issuer=user.issuer,
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


async def _create_test_job(
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    status: str = "queued",
) -> Job:
    job = Job(
        id=uuid.uuid4(),
        owner=str(principal.user_id),
        tenant_id=principal.tenant_id,
        owner_user_id=principal.user_id,
        status=status,
        version=1,
        source_ref="https://github.com/example/repo.git@main",
        source_revision="main",
        target_stack_spec={},
        budget={},
    )
    session.add(job)
    await session.flush()

    member = JobMember(
        job_id=job.id,
        membership_id=principal.membership_id,
    )
    session.add(member)
    await session.flush()
    return job


@pytest.mark.asyncio
async def test_workflow_reconciliation_with_postgresql(db_session: AsyncSession) -> None:
    """Verify workflow state transitions reconcile cleanly into PostgreSQL Job records and audit events."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available for reconciliation test")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")

    engine = WorkflowEngine()

    assert job.tenant_id is not None

    # 1. Start workflow: halts at G1 approval gate
    state = await engine.start_workflow(
        job_id=job.id,
        tenant_id=job.tenant_id,
        owner=job.owner,
        session=db_session,
    )

    await db_session.refresh(job)
    assert job.status == JobLifecycleState.AWAITING_APPROVAL.value
    assert state["needs_human"] is True
    assert state["current_gate"] == "G1_FEASIBILITY"

    # Verify audit event recorded
    audit_res = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM audit_event WHERE job_id = :jid AND action = 'WORKFLOW_STATE_AWAITING_APPROVAL'"
        ),
        {"jid": job.id},
    )
    assert (audit_res.scalar() or 0) >= 1

    # 2. Resume through all gates to completion
    await engine.resume_workflow(
        job_id=job.id,
        resume_payload={"decision": "approved", "actor": "lead"},
        session=db_session,
    )
    await engine.resume_workflow(
        job_id=job.id,
        resume_payload={"decision": "approved", "actor": "lead"},
        session=db_session,
    )
    await engine.resume_workflow(
        job_id=job.id,
        resume_payload={"decision": "approved", "actor": "lead"},
        session=db_session,
    )
    final_state = await engine.resume_workflow(
        job_id=job.id,
        resume_payload={"decision": "approved", "actor": "lead"},
        session=db_session,
    )

    await db_session.refresh(job)
    assert job.status == JobLifecycleState.COMPLETED.value
    assert job.current_stage == "completed"
    assert job.completed_at is not None
    assert final_state["status"] == JobLifecycleState.COMPLETED.value
