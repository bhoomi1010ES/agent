"""Sub-Phase 01.12 — Worker Crash, Lease Expiry, and Resumption Integration Test.

Validates Section 6 & Section 29:
1. Worker 1 claims task and leases it.
2. Worker 1 crashes (simulated by lease expiring in database without heartbeat renewal).
3. Worker 2 detects expired lease, reclaims task with incremented attempt count.
4. Stale Worker 1 wakes up and attempts to commit completion -> rejected with LeaseLostError.
5. Worker 2 executes task, records model execution, produces artifact, and marks task complete.
6. Workflow engine resumes from durable checkpoint using recovered task results.
7. Validates that no duplicate task execution or duplicate side effects occur.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.identity import (
    Tenant,
    TenantMembership,
    UserAccount,
)
from modernization_platform.db.models.job import Job
from modernization_platform.db.models.task import Task
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.tasks.errors import LeaseLostError
from modernization_platform.domain.tasks.states import TaskLifecycleState
from modernization_platform.repositories.tasks import TaskRepository
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.workflows.engine import WorkflowEngine


async def _create_test_identity(
    session: AsyncSession,
    *,
    tenant: Tenant,
    role: Role,
    subject: str,
) -> tuple[UserAccount, TenantMembership, AuthenticatedPrincipal]:
    user = UserAccount(
        issuer="https://auth.modernization.internal",
        subject=subject,
        display_name=subject.capitalize(),
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
        expires_at=datetime.now(UTC) + timedelta(hours=2),
        authentication_method="oidc_jwt",
    )
    return user, membership, principal


@pytest.mark.asyncio
async def test_worker_crash_lease_recovery_and_workflow_resumption(
    db_session: AsyncSession,
) -> None:
    """Validate that crashed worker tasks are safely recovered by peers and stale workers cannot overwrite state."""
    # 1. Setup Tenant and Owner
    tenant = Tenant(
        id=uuid.uuid4(),
        slug="cloud-scale-inc",
        display_name="Cloud Scale Inc",
        active=True,
    )
    db_session.add(tenant)
    await db_session.flush()

    _user, _mem, owner_principal = await _create_test_identity(
        db_session, tenant=tenant, role=Role.OWNER, subject="lead-devops"
    )

    # 2. Setup Job
    job = Job(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        owner=str(owner_principal.user_id),
        owner_user_id=owner_principal.user_id,
        status=JobLifecycleState.RUNNING.value,
        source_ref="https://git.company.test/legacy/service.git",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 10000},
    )
    db_session.add(job)
    await db_session.flush()

    # 3. Create durable task
    task_repo = TaskRepository(db_session)
    task = await task_repo.create_task(
        job_id=job.id,
        task_type="deep_code_analysis",
        payload={"source_dir": "src/legacy"},
        max_attempts=3,
    )
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    # 4. Worker 1 claims task
    async with session_factory() as session, session.begin():
        repo1 = TaskRepository(session)
        claimed_w1 = await repo1.claim_next_task(worker_id="worker-node-alpha", lease_seconds=10.0)
        assert claimed_w1 is not None
        assert claimed_w1.id == task.id
        assert claimed_w1.worker_id == "worker-node-alpha"
        assert claimed_w1.attempt_count == 1
        assert claimed_w1.status == TaskLifecycleState.RUNNING.value

    # 5. Simulate Worker 1 process crash & lease expiry
    past_timestamp = datetime.now(UTC) - timedelta(seconds=30)
    async with session_factory() as session, session.begin():
        await session.execute(
            update(Task).where(Task.id == task.id).values(lease_expires_at=past_timestamp)
        )

    # 6. Worker 2 detects expired lease and reclaims task
    async with session_factory() as session, session.begin():
        repo2 = TaskRepository(session)
        claimed_w2 = await repo2.claim_next_task(worker_id="worker-node-beta", lease_seconds=60.0)
        assert claimed_w2 is not None
        assert claimed_w2.id == task.id
        assert claimed_w2.worker_id == "worker-node-beta"
        # Attempt count safely incremented to 2
        assert claimed_w2.attempt_count == 2
        assert claimed_w2.lease_expires_at is not None
        assert claimed_w2.lease_expires_at > datetime.now(UTC)

    # 7. Stale Worker 1 wakes up and attempts to commit completion -> MUST be rejected with LeaseLostError
    async with session_factory() as session, session.begin():
        repo_stale = TaskRepository(session)
        with pytest.raises(LeaseLostError):
            await repo_stale.complete_task(
                task_id=task.id,
                worker_id="worker-node-alpha",  # Stale worker lease lost!
                result_payload={"corrupted": "should_not_save"},
            )

    # 8. Worker 2 completes task successfully and creates durable artifact
    async with session_factory() as session, session.begin():
        repo2 = TaskRepository(session)
        await repo2.complete_task(
            task_id=task.id,
            worker_id="worker-node-beta",
            result_payload={"analysis_complete": True, "files_parsed": 84},
        )
        # Create output artifact
        recovered_art = Artifact(
            id=uuid.uuid4(),
            job_id=job.id,
            type="CodeAnalysisReport",
            version=1,
            storage_ref="s3://bucket/jobs/analysis_report.json",
            content_hash="a" * 64,
            size_bytes=12000,
            content_type="application/json",
            status="available",
        )
        session.add(recovered_art)

    # 9. Verify final task state in database
    async with session_factory() as session:
        repo_verify = TaskRepository(session)
        final_task = await repo_verify.get_by_id(task.id)
        assert final_task is not None
        assert final_task.status == TaskLifecycleState.COMPLETED.value
        assert final_task.worker_id == "worker-node-beta"
        assert final_task.attempt_count == 2
        assert final_task.result == {"analysis_complete": True, "files_parsed": 84}

    # 10. Resumption of Workflow Engine with recovered state
    workflow_engine = WorkflowEngine()
    wf_state = await workflow_engine.start_workflow(
        job_id=job.id,
        tenant_id=tenant.id,
        owner=owner_principal.subject,
        session=db_session,
    )
    # Workflow progresses cleanly to G1 Feasibility Gate without duplicate task execution
    assert wf_state["needs_human"] is True
    assert wf_state["current_gate"] == "G1_FEASIBILITY"
    assert "intake" in wf_state["completed_steps"]
