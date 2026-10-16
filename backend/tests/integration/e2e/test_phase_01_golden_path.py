"""Sub-Phase 01.12 — Flagship End-to-End Golden Path Integration Test.

Validates the full integrated lifecycle across Sub-Phases 01.1 through 01.11:
1. Authentication & RBAC (Owner, Approver, Reviewer roles)
2. Job Creation & Persistence
3. LangGraph Workflow Execution & Durable Checkpointing
4. Task Creation & Worker Leases
5. Agent Step Dispatch via Provider-Neutral Model Gateway
6. Atomic Budget Reservation & Reconciled Usage
7. Durable Artifact Creation & Version Tracking
8. Four TDD Human Approval Gates (G1 Feasibility, G2 Characterization, G3 Blueprint, G4 Integration/PR)
9. Append-Only Gate Decisions & Reviewer Binding
10. Final Job Completion and Immutable Audit History
11. Durability across database connection reload
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.budget import BudgetAccount
from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.db.models.identity import (
    JobMember,
    Tenant,
    TenantMembership,
    UserAccount,
)
from modernization_platform.db.models.job import Job
from modernization_platform.db.models.task import Task
from modernization_platform.domain.gates.states import GateDecisionType, GateState
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.model_gateway.pricing import (
    ModelPricing,
    default_pricing_registry,
)
from modernization_platform.domain.tasks.states import TaskLifecycleState
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.budgets import BudgetRepository
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.repositories.model_executions import ModelExecutionRepository
from modernization_platform.repositories.tasks import TaskRepository
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.gates import GateService
from modernization_platform.workflows.agent_dispatch import dispatch_agent_step
from modernization_platform.workflows.engine import WorkflowEngine


async def _create_test_identity(
    session: AsyncSession,
    *,
    tenant: Tenant,
    role: Role,
    subject: str,
) -> tuple[UserAccount, TenantMembership, AuthenticatedPrincipal]:
    """Helper to create persistent test user, membership, and authenticated principal."""
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
async def test_sub_phase_01_full_lifecycle_golden_path(db_session: AsyncSession) -> None:
    """Execute and validate the complete Phase 1 Golden Path from Job Creation to Completion."""
    # -------------------------------------------------------------------------
    # 1. SETUP TENANT AND RBAC IDENTITIES (01.4 Authentication / RBAC)
    # -------------------------------------------------------------------------
    tenant = Tenant(
        id=uuid.uuid4(),
        slug="enterprise-corp",
        display_name="Enterprise Corp",
        active=True,
    )
    db_session.add(tenant)
    await db_session.flush()

    _owner_user, _owner_mem, owner_principal = await _create_test_identity(
        db_session, tenant=tenant, role=Role.OWNER, subject="lead-architect"
    )
    _approver_user, _approver_mem, approver_principal = await _create_test_identity(
        db_session, tenant=tenant, role=Role.APPROVER, subject="compliance-officer"
    )
    _reviewer_user, _reviewer_mem, reviewer_principal = await _create_test_identity(
        db_session, tenant=tenant, role=Role.REVIEWER, subject="qa-engineer"
    )

    # -------------------------------------------------------------------------
    # 2. JOB CREATION & BUDGET PROVISIONING (01.3 & 01.11)
    # -------------------------------------------------------------------------
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        tenant_id=tenant.id,
        owner=str(owner_principal.user_id),
        owner_user_id=owner_principal.user_id,
        status=JobLifecycleState.QUEUED.value,
        source_ref="https://git.company.test/legacy/core-monolith.git",
        target_stack_spec={"framework": "fastapi", "runtime": "python3.12"},
        budget={"max_cost_cents": 50000},
    )
    db_session.add(job)
    await db_session.flush()

    # Assign reviewer and approver to the job (RBAC job membership)
    db_session.add(JobMember(job_id=job.id, membership_id=approver_principal.membership_id))
    db_session.add(JobMember(job_id=job.id, membership_id=reviewer_principal.membership_id))
    await db_session.flush()

    # Initial budget account: $500.00 (50,000,000 microcents)
    budget_account = BudgetAccount(
        id=uuid.uuid4(),
        job_id=job.id,
        scope_type="job",
        scope_id="job",
        limit_microcents=50_000_000,
        spent_microcents=0,
        reserved_microcents=0,
        warning_threshold_percent=80,
        warning_emitted=False,
        status="active",
    )
    db_session.add(budget_account)
    await db_session.flush()

    # Log initial audit event
    audit_repo = AuditEventRepository(db_session)
    await audit_repo.append_event(
        actor=owner_principal.subject,
        actor_user_id=owner_principal.user_id,
        action="JOB_CREATED",
        job_id=job.id,
        correlation_id="corr-init",
        payload={"source_ref": job.source_ref, "budget_limit": 50000},
    )
    await db_session.commit()

    # Configure active model pricing for mock provider to record non-zero financial spend
    default_pricing_registry.register_pricing(
        ModelPricing(
            provider="mock",
            model_id="mock-model",
            input_microcents_per_1k=150,
            output_microcents_per_1k=600,
        )
    )

    # -------------------------------------------------------------------------
    # 3. WORKFLOW ENGINE INITIALIZATION (01.6 & 01.10)
    # -------------------------------------------------------------------------
    workflow_engine = WorkflowEngine()
    gate_service = GateService(session=db_session, workflow_engine=workflow_engine)

    # -------------------------------------------------------------------------
    # 4. START WORKFLOW: INTAKE & G1 FEASIBILITY GATE
    # -------------------------------------------------------------------------
    wf_state_1 = await workflow_engine.start_workflow(
        job_id=job.id,
        tenant_id=tenant.id,
        owner=owner_principal.subject,
        session=db_session,
    )
    assert wf_state_1["needs_human"] is True
    assert wf_state_1["current_gate"] == "G1_FEASIBILITY"
    assert "intake" in wf_state_1["completed_steps"]

    # Durable task creation & lease (01.9)
    task_repo = TaskRepository(db_session)
    t1 = await task_repo.create_task(job_id=job.id, task_type="feasibility_agent_step")
    claimed_t1 = await task_repo.claim_next_task(worker_id="worker-node-1", lease_seconds=60.0)
    assert claimed_t1 is not None
    assert claimed_t1.id == t1.id

    # Agent step dispatch via Model Gateway (01.11)
    agent_response_1 = await dispatch_agent_step(
        session=db_session,
        job_id=job.id,
        task_id=t1.id,
        agent_role="architect",
        prompt="Analyze monolithic dependencies and verify feasibility.",
        prompt_version="feasibility-v1.0",
    )
    assert agent_response_1.content != ""
    assert agent_response_1.usage.total_tokens > 0

    # Complete worker task
    await task_repo.complete_task(
        task_id=t1.id,
        worker_id="worker-node-1",
        result_payload={"feasibility_score": 0.94},
    )

    # Persist Feasibility Artifact (01.8)
    art_1 = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="FeasibilityAssessment",
        version=1,
        storage_ref="s3://bucket/jobs/feasibility_v1.json",
        content_hash="1" * 64,
        size_bytes=4096,
        content_type="application/json",
        status="available",
    )
    db_session.add(art_1)
    await db_session.flush()
    await db_session.commit()

    # Create durable Human Gate G1 with exact artifact version binding (01.10)
    gate_g1 = await gate_service.create_gate(
        principal=owner_principal,
        job_id=job.id,
        gate_type="G1_FEASIBILITY",
        artifact_versions_shown={"FeasibilityAssessment": art_1.version},
        timeout_seconds=3600,
    )
    await db_session.commit()

    # Approver approves Gate G1
    dec_g1 = await gate_service.decide_gate(
        principal=approver_principal,
        gate_id=gate_g1.id,
        decision="approved",
        reason="Architecture feasibility confirmed by compliance review.",
    )
    assert dec_g1.decision == GateDecisionType.APPROVED.value
    await db_session.commit()

    # -------------------------------------------------------------------------
    # 5. ADVANCE WORKFLOW: ANALYSIS & G2 CHARACTERIZATION GATE
    # -------------------------------------------------------------------------
    wf_state_2 = await workflow_engine.get_state(job.id)
    assert wf_state_2 is not None
    assert wf_state_2["needs_human"] is True
    assert wf_state_2["current_gate"] == "G2_CHARACTERIZATION"
    assert "analysis" in wf_state_2["completed_steps"]

    # Dispatch agent for characterization
    t2 = await task_repo.create_task(job_id=job.id, task_type="characterization_agent_step")
    claimed_t2 = await task_repo.claim_next_task(worker_id="worker-node-2", lease_seconds=60.0)
    assert claimed_t2 is not None

    agent_response_2 = await dispatch_agent_step(
        session=db_session,
        job_id=job.id,
        task_id=t2.id,
        agent_role="architect",
        prompt="Characterize legacy modules, APIs, and data flows.",
        prompt_version="characterize-v1.0",
    )
    assert agent_response_2.content != ""

    await task_repo.complete_task(
        task_id=t2.id,
        worker_id="worker-node-2",
        result_payload={"modules_identified": 12},
    )

    art_2 = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="CharacterizationReport",
        version=1,
        storage_ref="s3://bucket/jobs/characterization_v1.json",
        content_hash="2" * 64,
        size_bytes=8192,
        content_type="application/json",
        status="available",
    )
    db_session.add(art_2)
    await db_session.flush()
    await db_session.commit()

    gate_g2 = await gate_service.create_gate(
        principal=owner_principal,
        job_id=job.id,
        gate_type="G2_CHARACTERIZATION",
        artifact_versions_shown={"CharacterizationReport": art_2.version},
        timeout_seconds=3600,
    )
    await db_session.commit()

    dec_g2 = await gate_service.decide_gate(
        principal=approver_principal,
        gate_id=gate_g2.id,
        decision="approved",
        reason="Module characterization and boundary contracts accepted.",
    )
    assert dec_g2.decision == GateDecisionType.APPROVED.value
    await db_session.commit()

    # -------------------------------------------------------------------------
    # 6. ADVANCE WORKFLOW: ARCHITECTURE & G3 BLUEPRINT/PLAN GATE
    # -------------------------------------------------------------------------
    wf_state_3 = await workflow_engine.get_state(job.id)
    assert wf_state_3 is not None
    assert wf_state_3["needs_human"] is True
    assert wf_state_3["current_gate"] == "G3_BLUEPRINT_PLAN"
    assert "architecture" in wf_state_3["completed_steps"]

    t3 = await task_repo.create_task(job_id=job.id, task_type="blueprint_agent_step")
    claimed_t3 = await task_repo.claim_next_task(worker_id="worker-node-1", lease_seconds=60.0)
    assert claimed_t3 is not None

    agent_response_3 = await dispatch_agent_step(
        session=db_session,
        job_id=job.id,
        task_id=t3.id,
        agent_role="architect",
        prompt="Generate comprehensive modernization blueprint and migration plan.",
        prompt_version="blueprint-v1.0",
    )
    assert agent_response_3.content != ""

    await task_repo.complete_task(
        task_id=t3.id,
        worker_id="worker-node-1",
        result_payload={"migration_phases": 4},
    )

    art_3 = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="ModernizationBlueprint",
        version=1,
        storage_ref="s3://bucket/jobs/blueprint_v1.json",
        content_hash="3" * 64,
        size_bytes=16384,
        content_type="application/json",
        status="available",
    )
    db_session.add(art_3)
    await db_session.flush()
    await db_session.commit()

    gate_g3 = await gate_service.create_gate(
        principal=owner_principal,
        job_id=job.id,
        gate_type="G3_BLUEPRINT_PLAN",
        artifact_versions_shown={"ModernizationBlueprint": art_3.version},
        timeout_seconds=3600,
    )
    await db_session.commit()

    dec_g3 = await gate_service.decide_gate(
        principal=approver_principal,
        gate_id=gate_g3.id,
        decision="approved",
        reason="Target stack architecture and blueprint ratified.",
    )
    assert dec_g3.decision == GateDecisionType.APPROVED.value
    await db_session.commit()

    # -------------------------------------------------------------------------
    # 7. ADVANCE WORKFLOW: EXECUTION & G4 INTEGRATION/PR GATE
    # -------------------------------------------------------------------------
    wf_state_4 = await workflow_engine.get_state(job.id)
    assert wf_state_4 is not None
    assert wf_state_4["needs_human"] is True
    assert wf_state_4["current_gate"] == "G4_INTEGRATION_PR"
    assert "conversion" in wf_state_4["completed_steps"]
    assert "verification" in wf_state_4["completed_steps"]

    t4 = await task_repo.create_task(job_id=job.id, task_type="pr_generation_agent_step")
    claimed_t4 = await task_repo.claim_next_task(worker_id="worker-node-3", lease_seconds=60.0)
    assert claimed_t4 is not None

    agent_response_4 = await dispatch_agent_step(
        session=db_session,
        job_id=job.id,
        task_id=t4.id,
        agent_role="engineer",
        prompt="Generate modernized pull request with test suite and migration scripts.",
        prompt_version="codegen-v1.0",
    )
    assert agent_response_4.content != ""

    await task_repo.complete_task(
        task_id=t4.id,
        worker_id="worker-node-3",
        result_payload={"pr_branch": "modernize/phase-1-core"},
    )

    art_4 = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="ModernizedPullRequest",
        version=1,
        storage_ref="s3://bucket/jobs/pr_patch_v1.diff",
        content_hash="4" * 64,
        size_bytes=32768,
        content_type="text/x-diff",
        status="available",
    )
    db_session.add(art_4)
    await db_session.flush()
    await db_session.commit()

    gate_g4 = await gate_service.create_gate(
        principal=owner_principal,
        job_id=job.id,
        gate_type="G4_INTEGRATION_PR",
        artifact_versions_shown={"ModernizedPullRequest": art_4.version},
        timeout_seconds=3600,
    )
    await db_session.commit()

    # Approver approves final Gate G4
    dec_g4 = await gate_service.decide_gate(
        principal=approver_principal,
        gate_id=gate_g4.id,
        decision="approved",
        reason="PR passes automated verification and security audit; approved for deployment.",
    )
    assert dec_g4.decision == GateDecisionType.APPROVED.value
    await db_session.commit()

    # -------------------------------------------------------------------------
    # 8. FINAL WORKFLOW COMPLETION VALIDATION
    # -------------------------------------------------------------------------
    final_wf_state = await workflow_engine.get_state(job.id)
    assert final_wf_state is not None
    assert final_wf_state["needs_human"] is False
    assert final_wf_state["current_gate"] is None
    assert final_wf_state["status"] == JobLifecycleState.COMPLETED.value
    assert "completed" in final_wf_state["completed_steps"]

    # Verify all 4 gate approvals are durably registered in the workflow state
    assert len(final_wf_state["gate_approvals"]) == 4
    for gate_name in [
        "G1_FEASIBILITY",
        "G2_CHARACTERIZATION",
        "G3_BLUEPRINT_PLAN",
        "G4_INTEGRATION_PR",
    ]:
        assert gate_name in final_wf_state["gate_approvals"]
        assert final_wf_state["gate_approvals"][gate_name]["decision"] == "approved"

    # -------------------------------------------------------------------------
    # 9. RECONCILE AND VERIFY DURABLE DATABASE ENTITIES
    # -------------------------------------------------------------------------
    job_repo = JobRepository(db_session)
    await job_repo.update_status(job.id, JobLifecycleState.COMPLETED)
    await audit_repo.append_event(
        actor="system:workflow",
        action="JOB_COMPLETED",
        job_id=job.id,
        correlation_id="corr-final",
        payload={"completed_steps": final_wf_state["completed_steps"]},
    )
    await db_session.commit()

    # 10. VALIDATE MODEL EXECUTIONS & SPEND
    exec_repo = ModelExecutionRepository(db_session)
    executions = await exec_repo.list_for_job(job.id)
    assert len(executions) == 4
    total_spend_microcents = sum(e.actual_cost_microcents for e in executions)
    assert total_spend_microcents > 0

    # 11. VALIDATE ATOMIC BUDGET ACCOUNT
    budget_repo = BudgetRepository(db_session)
    account = await budget_repo.get_account_by_job_for_update(job_id=job.id)
    assert account is not None
    assert account.spent_microcents == total_spend_microcents
    assert account.reserved_microcents == 0
    assert account.spent_microcents <= account.limit_microcents

    # 12. VALIDATE IMMUTABLE AUDIT TRAIL
    audit_events = await audit_repo.list_events_by_job(job.id)
    action_types = {e.action for e in audit_events}
    assert "JOB_CREATED" in action_types
    assert "GATE_CREATED" in action_types
    assert "GATE_APPROVED" in action_types
    assert "JOB_COMPLETED" in action_types

    # 13. RELOAD FROM CLEAN SESSION (Durability across restart)
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    async with session_factory() as verify_session:
        # Verify Job
        reloaded_job = await verify_session.get(Job, job.id)
        assert reloaded_job is not None
        assert reloaded_job.status == JobLifecycleState.COMPLETED.value

        # Verify Gates & Decisions
        gates_result = await verify_session.execute(
            select(Gate).where(Gate.job_id == job.id).order_by(Gate.requested_at)
        )
        persisted_gates = list(gates_result.scalars().all())
        assert len(persisted_gates) == 4
        assert all(g.state == GateState.APPROVED.value for g in persisted_gates)

        decisions_result = await verify_session.execute(
            select(GateDecision)
            .join(Gate, GateDecision.gate_id == Gate.id)
            .where(Gate.job_id == job.id)
        )
        persisted_decisions = list(decisions_result.scalars().all())
        assert len(persisted_decisions) == 4
        assert all(d.decision == "approved" for d in persisted_decisions)

        # Verify Tasks
        tasks_result = await verify_session.execute(select(Task).where(Task.job_id == job.id))
        persisted_tasks = list(tasks_result.scalars().all())
        assert len(persisted_tasks) == 4
        assert all(t.status == TaskLifecycleState.COMPLETED.value for t in persisted_tasks)

        # Verify Artifacts
        artifacts_result = await verify_session.execute(
            select(Artifact).where(Artifact.job_id == job.id)
        )
        persisted_artifacts = list(artifacts_result.scalars().all())
        assert len(persisted_artifacts) == 4
