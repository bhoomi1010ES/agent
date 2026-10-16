"""PostgreSQL integration tests for gate timeout-to-paused behavior and reconciliation."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.domain.gates.errors import GateTimeoutError
from modernization_platform.domain.gates.states import GateState
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.security.permissions import Role
from modernization_platform.services.gates import GateService
from tests.integration.db.conftest import _PORT_AVAILABLE, _skip_or_fail_database
from tests.integration.gates.conftest import (
    create_gate_test_job,
    create_gate_test_principal,
)


@pytest.mark.asyncio
async def test_gate_timeout_transitions_to_paused_never_approved(
    db_session: AsyncSession,
) -> None:
    """When gate.timeout_at passes, reconciliation transitions gate and job to paused; never approved."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await create_gate_test_principal(db_session, Role.APPROVER)
    job = await create_gate_test_job(
        db_session, principal, status=JobLifecycleState.AWAITING_APPROVAL.value
    )
    await db_session.commit()

    service = GateService(db_session)
    gate = await service.create_gate(
        principal=principal,
        job_id=job.id,
        gate_type="G1_FEASIBILITY",
        timeout_seconds=60,
    )
    # Manually backdate timeout_at to simulate time passing across restart
    past_timeout = datetime.now(UTC) - timedelta(minutes=5)
    gate.timeout_at = past_timeout
    await db_session.commit()

    # Worker/Reconciliation scans for expired gates
    paused_gates = await service.check_and_handle_timeouts()
    await db_session.commit()

    assert len(paused_gates) >= 1
    assert any(g.id == gate.id for g in paused_gates)

    # Verify gate state is PAUSED, definitely NOT approved
    reloaded_gate = await service.get_gate(principal=principal, gate_id=gate.id, job_id=job.id)
    assert reloaded_gate.state == GateState.PAUSED.value
    assert reloaded_gate.state != GateState.APPROVED.value

    # Verify parent job state was reconciled to PAUSED
    reloaded_job = await service._jobs._get_by_id_unscoped(job.id)
    assert reloaded_job is not None
    assert reloaded_job.status == JobLifecycleState.PAUSED.value


@pytest.mark.asyncio
async def test_decision_on_expired_gate_fails_and_pauses(db_session: AsyncSession) -> None:
    """Attempting to decide a gate whose timeout has expired raises GateTimeoutError and marks it paused."""
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
        timeout_seconds=10,
    )
    # Set expired timeout
    gate.timeout_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    with pytest.raises(GateTimeoutError):
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            job_id=job.id,
            decision="approved",
            reason="Late approval attempt",
        )
    await db_session.commit()

    reloaded = await service.get_gate(principal=principal, gate_id=gate.id)
    assert reloaded.state == GateState.PAUSED.value


@pytest.mark.asyncio
async def test_paused_gate_can_be_resumed_and_decided(db_session: AsyncSession) -> None:
    """A gate paused after timeout can be resumed by an authorized reviewer and then approved."""
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
    # Force state to PAUSED
    gate.state = GateState.PAUSED.value
    await db_session.commit()

    # 1. Resume gate back to pending
    resumed_gate = await service.resume_gate(
        principal=principal,
        gate_id=gate.id,
        job_id=job.id,
        reason="Resuming after timeout review",
    )
    await db_session.commit()
    assert resumed_gate.state == GateState.PENDING.value

    # 2. Can now successfully approve
    decision = await service.decide_gate(
        principal=principal,
        gate_id=gate.id,
        job_id=job.id,
        decision="approved",
        reason="Approved after resume",
    )
    await db_session.commit()
    assert decision.decision == "approved"

    final_gate = await service.get_gate(principal=principal, gate_id=gate.id)
    assert final_gate.state == GateState.APPROVED.value
