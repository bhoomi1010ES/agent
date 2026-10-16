"""PostgreSQL integration tests for Gate lifecycle, immutable audit decisions, and authorization."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.core.exceptions import ForbiddenException
from modernization_platform.domain.gates.errors import (
    DuplicateDecisionError,
    MissingRejectionRationaleError,
    StaleArtifactVersionError,
)
from modernization_platform.domain.gates.states import GateDecisionType, GateState
from modernization_platform.security.permissions import Role
from modernization_platform.services.gates import GateService
from tests.integration.db.conftest import _PORT_AVAILABLE, _skip_or_fail_database
from tests.integration.gates.conftest import (
    create_gate_test_artifact,
    create_gate_test_job,
    create_gate_test_principal,
)


@pytest.mark.asyncio
async def test_gate_create_and_retrieve_lifecycle(db_session: AsyncSession) -> None:
    """Verify durable creation, retrieval, and fields of an approval gate in PostgreSQL."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await create_gate_test_principal(db_session, Role.APPROVER)
    job = await create_gate_test_job(db_session, principal)
    artifact = await create_gate_test_artifact(db_session, job.id, "SPECIFICATION", version=1)
    await db_session.commit()

    service = GateService(db_session)
    gate = await service.create_gate(
        principal=principal,
        job_id=job.id,
        gate_type="G1_FEASIBILITY",
        timeout_seconds=3600,
        artifact_versions_shown={str(artifact.id): 1},
        needs_human_flags=[{"code": "COST_UNCERTAINTY", "severity": "medium"}],
        budget_used_cents=120.50,
    )
    await db_session.commit()

    assert gate.id is not None
    assert gate.state == GateState.PENDING.value
    assert gate.timeout_at is not None
    assert gate.artifact_versions_shown == {str(artifact.id): 1}

    # Retrieve from DB using fresh query
    fetched_gate = await service.get_gate(principal=principal, gate_id=gate.id, job_id=job.id)
    assert fetched_gate.id == gate.id
    assert fetched_gate.gate_type == "G1_FEASIBILITY"
    assert fetched_gate.state == "pending"
    assert fetched_gate.budget_used_cents == 120.50


@pytest.mark.asyncio
async def test_gate_approval_persists_immutable_decision_history(
    db_session: AsyncSession,
) -> None:
    """Authorized reviewer approves pending gate; creates append-only decision record."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await create_gate_test_principal(db_session, Role.APPROVER)
    job = await create_gate_test_job(db_session, principal)
    artifact = await create_gate_test_artifact(db_session, job.id, "SPECIFICATION", version=1)
    await db_session.commit()

    service = GateService(db_session)
    gate = await service.create_gate(
        principal=principal,
        job_id=job.id,
        gate_type="G1_FEASIBILITY",
        artifact_versions_shown={str(artifact.id): 1},
    )
    await db_session.commit()

    # Approve gate
    decision = await service.decide_gate(
        principal=principal,
        gate_id=gate.id,
        job_id=job.id,
        decision=GateDecisionType.APPROVED.value,
        reason="Approved after thorough verification.",
        artifact_versions={str(artifact.id): 1},
    )
    await db_session.commit()

    assert decision.id is not None
    assert decision.gate_id == gate.id
    assert decision.job_id == job.id
    assert decision.decision == "approved"
    assert decision.actor_user_id == principal.user_id
    assert decision.approver_role == Role.APPROVER.value
    assert decision.feedback == "Approved after thorough verification."

    # Simulate process restart by reloading from clean session
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    async with session_factory() as clean_session:
        clean_service = GateService(clean_session)
        reloaded_gate = await clean_service.get_gate(
            principal=principal, gate_id=gate.id, job_id=job.id
        )
        assert reloaded_gate.state == GateState.APPROVED.value
        assert reloaded_gate.resolved_at is not None
        assert reloaded_gate.resolved_by_user_id == principal.user_id

        # Verify decision history
        decisions = await clean_service.list_gate_decisions(
            principal=principal, gate_id=gate.id, job_id=job.id
        )
        assert len(decisions) == 1
        assert decisions[0].decision == "approved"
        assert decisions[0].artifact_version_refs == {str(artifact.id): 1}


@pytest.mark.asyncio
async def test_gate_rejection_requires_written_feedback(db_session: AsyncSession) -> None:
    """Rejection fails when rationale is missing; succeeds when valid feedback is supplied."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await create_gate_test_principal(db_session, Role.APPROVER)
    job = await create_gate_test_job(db_session, principal)
    await db_session.commit()

    service = GateService(db_session)
    gate = await service.create_gate(
        principal=principal,
        job_id=job.id,
        gate_type="G2_CHARACTERIZATION",
    )
    await db_session.commit()

    # 1. Blank rejection rationale fails
    with pytest.raises(MissingRejectionRationaleError):
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            job_id=job.id,
            decision="rejected",
            reason="   ",
        )

    # 2. Rejection with valid rationale succeeds
    decision = await service.decide_gate(
        principal=principal,
        gate_id=gate.id,
        job_id=job.id,
        decision="rejected",
        reason="Missing regression test suite for batch accounts.",
        return_to_stage=True,
    )
    await db_session.commit()

    assert decision.decision == "rejected"
    assert decision.feedback == "Missing regression test suite for batch accounts."

    # Verify gate state is rejected
    reloaded_gate = await service.get_gate(principal=principal, gate_id=gate.id, job_id=job.id)
    assert reloaded_gate.state == GateState.REJECTED.value


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_decide_gate(db_session: AsyncSession) -> None:
    """User without GATE_DECIDE permission (e.g. REVIEWER) cannot approve or reject gates."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    approver = await create_gate_test_principal(db_session, Role.APPROVER)
    reviewer = await create_gate_test_principal(db_session, Role.REVIEWER)
    job = await create_gate_test_job(db_session, approver)
    await db_session.commit()

    service = GateService(db_session)
    gate = await service.create_gate(
        principal=approver,
        job_id=job.id,
        gate_type="G1_FEASIBILITY",
    )
    await db_session.commit()

    with pytest.raises(ForbiddenException):
        await service.decide_gate(
            principal=reviewer,
            gate_id=gate.id,
            decision="approved",
            reason="I am only a reviewer",
        )


@pytest.mark.asyncio
async def test_duplicate_and_conflicting_decisions_prevented(
    db_session: AsyncSession,
) -> None:
    """Cannot approve after approval, nor reject after approval, nor approve after rejection."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await create_gate_test_principal(db_session, Role.APPROVER)
    job = await create_gate_test_job(db_session, principal)
    await db_session.commit()

    service = GateService(db_session)
    gate = await service.create_gate(
        principal=principal,
        job_id=job.id,
        gate_type="G3_BLUEPRINT_PLAN",
    )
    await db_session.commit()

    # Initial approval
    await service.decide_gate(
        principal=principal,
        gate_id=gate.id,
        job_id=job.id,
        decision="approved",
        reason="First approval",
    )
    await db_session.commit()

    # Attempt duplicate approval
    with pytest.raises(DuplicateDecisionError):
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            job_id=job.id,
            decision="approved",
            reason="Second approval attempt",
        )

    # Attempt rejection after approval
    with pytest.raises(DuplicateDecisionError):
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            job_id=job.id,
            decision="rejected",
            reason="Attempted reversal",
        )


@pytest.mark.asyncio
async def test_stale_artifact_version_approval_rejected(db_session: AsyncSession) -> None:
    """If an artifact advances in PostgreSQL after gate creation, stale approval is rejected."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await create_gate_test_principal(db_session, Role.APPROVER)
    job = await create_gate_test_job(db_session, principal)
    artifact = await create_gate_test_artifact(db_session, job.id, "SPECIFICATION", version=1)
    await db_session.commit()

    service = GateService(db_session)
    gate = await service.create_gate(
        principal=principal,
        job_id=job.id,
        gate_type="G1_FEASIBILITY",
        artifact_versions_shown={str(artifact.id): 1},
    )
    await db_session.commit()

    # Artifact advances to version 2 in PostgreSQL while gate is pending
    artifact.version = 2
    await db_session.commit()

    # Approver attempts to approve: service detects stale version and rejects
    with pytest.raises(StaleArtifactVersionError) as exc_info:
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            job_id=job.id,
            decision="approved",
        )
    assert exc_info.value.code == "STALE_ARTIFACT_VERSION"

    # Verify gate state remained pending and was not modified
    reloaded_gate = await service.get_gate(principal=principal, gate_id=gate.id, job_id=job.id)
    assert reloaded_gate.state == GateState.PENDING.value
