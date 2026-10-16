"""Sub-Phase 01.12 — Gate Rejection, Mandatory Rationale, and Rework Lifecycle Validation.

Validates:
1. Rejection without rationale is rejected with MissingRejectionRationaleError.
2. Reviewer or unauthorized role attempting decision is rejected with ForbiddenException.
3. Valid rejection transitions Gate to REJECTED and rolls back workflow to designated stage.
4. Rework produces next artifact version (v2).
5. Attempting to approve stale artifact version raises StaleArtifactVersionError.
6. Re-submitted gate with updated artifact version succeeds and advances workflow.
7. Both decisions exist in append-only immutable GateDecision history.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.core.exceptions import ForbiddenException
from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.db.models.identity import (
    JobMember,
    Tenant,
    TenantMembership,
    UserAccount,
)
from modernization_platform.db.models.job import Job
from modernization_platform.domain.gates.errors import (
    MissingRejectionRationaleError,
    StaleArtifactVersionError,
)
from modernization_platform.domain.gates.states import GateDecisionType, GateState
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.gates import GateService
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
async def test_gate_rejection_mandates_rationale_and_enables_rework_flow(
    db_session: AsyncSession,
) -> None:
    """Validate gate rejection safeguards, workflow rollback, artifact version bumping, and rework resumption."""
    # 1. Setup Tenant and Identities
    tenant = Tenant(
        id=uuid.uuid4(),
        slug="fintech-solutions",
        display_name="FinTech Solutions",
        active=True,
    )
    db_session.add(tenant)
    await db_session.flush()

    _owner_user, _owner_mem, owner_principal = await _create_test_identity(
        db_session, tenant=tenant, role=Role.OWNER, subject="lead-dev"
    )
    _approver_user, _approver_mem, approver_principal = await _create_test_identity(
        db_session, tenant=tenant, role=Role.APPROVER, subject="compliance-officer"
    )
    _reviewer_user, _reviewer_mem, reviewer_principal = await _create_test_identity(
        db_session, tenant=tenant, role=Role.REVIEWER, subject="qa-inspector"
    )

    # 2. Setup Job & Membership
    job = Job(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        owner=str(owner_principal.user_id),
        owner_user_id=owner_principal.user_id,
        status=JobLifecycleState.RUNNING.value,
        source_ref="https://git.fintech.test/legacy/ledger.git",
        target_stack_spec={"framework": "fastapi"},
        budget={"max_cost_cents": 25000},
    )
    db_session.add(job)
    await db_session.flush()

    db_session.add(JobMember(job_id=job.id, membership_id=approver_principal.membership_id))
    db_session.add(JobMember(job_id=job.id, membership_id=reviewer_principal.membership_id))
    await db_session.flush()

    # 3. Setup Workflow Engine & Gate Service
    workflow_engine = WorkflowEngine()
    gate_service = GateService(session=db_session, workflow_engine=workflow_engine)

    # Start workflow and approve G1 to reach G2 (Characterization)
    await workflow_engine.start_workflow(
        job_id=job.id,
        tenant_id=tenant.id,
        owner=owner_principal.subject,
        session=db_session,
    )
    # Approve G1
    await workflow_engine.resume_workflow(
        job_id=job.id,
        resume_payload={"decision": "approved", "actor": approver_principal.subject},
    )

    wf_state_g2 = await workflow_engine.get_state(job.id)
    assert wf_state_g2 is not None
    assert wf_state_g2["current_gate"] == "G2_CHARACTERIZATION"

    # Persist Characterization Report v1
    art_v1 = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="CharacterizationReport",
        version=1,
        storage_ref="s3://bucket/jobs/char_v1.json",
        content_hash="1" * 64,
        size_bytes=4096,
        content_type="application/json",
        status="available",
    )
    db_session.add(art_v1)
    await db_session.flush()

    # Create Gate G2 in database bound to artifact v1
    gate_g2_initial = await gate_service.create_gate(
        principal=owner_principal,
        job_id=job.id,
        gate_type="G2_CHARACTERIZATION",
        artifact_versions_shown={"CharacterizationReport": art_v1.version},
        timeout_seconds=3600,
    )
    await db_session.commit()

    # 4. TEST GUARD 1: Rejection without written rationale MUST fail
    with pytest.raises(MissingRejectionRationaleError):
        await gate_service.decide_gate(
            principal=approver_principal,
            gate_id=gate_g2_initial.id,
            decision="rejected",
            reason="",  # Empty rationale rejected
        )

    # 5. TEST GUARD 2: Reviewer role lacks GATE_DECIDE permission
    with pytest.raises(ForbiddenException):
        await gate_service.decide_gate(
            principal=reviewer_principal,
            gate_id=gate_g2_initial.id,
            decision="approved",
            reason="Approved by reviewer without approver role",
        )

    # 6. REJECTION EXECUTION WITH MANDATORY REASON
    rejection_reason = "Data migration schema lacks transaction boundary definitions."
    rej_dec = await gate_service.decide_gate(
        principal=approver_principal,
        gate_id=gate_g2_initial.id,
        decision="rejected",
        reason=rejection_reason,
        return_to_stage=True,
        rejection_target="analysis",
    )
    assert rej_dec.decision == GateDecisionType.REJECTED.value
    await db_session.commit()

    # Verify Gate G2 state is REJECTED
    reloaded_g2 = await gate_service.get_gate(principal=owner_principal, gate_id=gate_g2_initial.id)
    assert reloaded_g2.state == GateState.REJECTED.value

    # Verify workflow state rolled back to analysis and re-reached G2 with rejection history
    wf_state_rolled_back = await workflow_engine.get_state(job.id)
    assert wf_state_rolled_back is not None
    assert wf_state_rolled_back["needs_human"] is True
    assert wf_state_rolled_back["current_gate"] == "G2_CHARACTERIZATION"
    assert len(wf_state_rolled_back.get("rejection_history", [])) == 1
    assert wf_state_rolled_back["rejection_history"][0]["gate_type"] == "G2_CHARACTERIZATION"
    assert rejection_reason in wf_state_rolled_back["rejection_history"][0]["feedback"]

    # 7. REWORK: Create Characterization Report version 2 with fixes
    art_v2 = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="CharacterizationReport",
        version=2,
        storage_ref="s3://bucket/jobs/char_v2.json",
        content_hash="2" * 64,
        size_bytes=6144,
        content_type="application/json",
        status="available",
    )
    db_session.add(art_v2)
    await db_session.flush()
    await db_session.commit()

    # Create new Gate G2 reflecting the rework
    gate_g2_rework = await gate_service.create_gate(
        principal=owner_principal,
        job_id=job.id,
        gate_type="G2_CHARACTERIZATION",
        artifact_versions_shown={"CharacterizationReport": art_v2.version},
        timeout_seconds=3600,
    )
    await db_session.commit()

    # 8. TEST GUARD 3: Attempting decision against stale version 1 fails
    with pytest.raises(StaleArtifactVersionError):
        await gate_service.decide_gate(
            principal=approver_principal,
            gate_id=gate_g2_rework.id,
            decision="approved",
            reason="Trying to approve old version",
            artifact_versions={"CharacterizationReport": 1},  # Version 1 is stale! Max in DB is 2
        )

    # 9. APPROVAL WITH CURRENT ARTIFACT VERSION (v2)
    appr_dec = await gate_service.decide_gate(
        principal=approver_principal,
        gate_id=gate_g2_rework.id,
        decision="approved",
        reason="Revised data migration transaction boundaries verified and approved.",
        artifact_versions={"CharacterizationReport": 2},
    )
    assert appr_dec.decision == GateDecisionType.APPROVED.value
    await db_session.commit()

    # 10. VERIFY WORKFLOW ADVANCES FORWARD TO ARCHITECTURE & G3
    wf_state_forward = await workflow_engine.get_state(job.id)
    assert wf_state_forward is not None
    assert wf_state_forward["current_gate"] == "G3_BLUEPRINT_PLAN"
    assert "architecture" in wf_state_forward["completed_steps"]

    # 11. VERIFY APPEND-ONLY AUDIT DECISION RECORDS
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    async with session_factory() as verify_session:
        decisions_stmt = (
            select(GateDecision)
            .join(Gate, GateDecision.gate_id == Gate.id)
            .where(Gate.job_id == job.id)
            .order_by(GateDecision.decided_at.asc())
        )
        decisions_res = await verify_session.execute(decisions_stmt)
        decisions = list(decisions_res.scalars().all())

        assert len(decisions) == 2
        assert decisions[0].decision == "rejected"
        assert decisions[0].feedback == rejection_reason
        assert decisions[1].decision == "approved"
        assert decisions[1].feedback is not None
        assert "transaction boundaries verified" in decisions[1].feedback
