"""PostgreSQL integration tests verifying concurrent decision isolation and row locking."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.domain.gates.errors import DuplicateDecisionError, GateClosedError
from modernization_platform.domain.gates.states import GateState
from modernization_platform.security.permissions import Role
from modernization_platform.services.gates import GateService
from tests.integration.db.conftest import _PORT_AVAILABLE, _skip_or_fail_database
from tests.integration.gates.conftest import (
    create_gate_test_job,
    create_gate_test_principal,
)


@pytest.mark.asyncio
async def test_concurrent_decisions_on_same_gate_result_in_exactly_one_success(
    db_session: AsyncSession,
) -> None:
    """Two concurrent decisions on the same gate under row locking result in exactly 1 winner and 1 conflict."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await create_gate_test_principal(db_session, Role.APPROVER)
    job = await create_gate_test_job(db_session, principal)
    await db_session.commit()

    service = GateService(db_session)
    gate = await service.create_gate(
        principal=principal,
        job_id=job.id,
        gate_type="G1_FEASIBILITY",
    )
    await db_session.commit()
    gate_id = gate.id

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    async def attempt_decision(attempt_id: str) -> str:
        async with session_factory() as session:
            gate_svc = GateService(session)
            try:
                await gate_svc.decide_gate(
                    principal=principal,
                    gate_id=gate_id,
                    decision="approved",
                    reason=f"Concurrent approval attempt {attempt_id}",
                )
                await session.commit()
                return "SUCCESS"
            except (DuplicateDecisionError, GateClosedError):
                await session.rollback()
                return "CONFLICT"

    # Launch both decision attempts concurrently
    results = await asyncio.gather(
        attempt_decision("worker_A"),
        attempt_decision("worker_B"),
    )

    # Exactly one must succeed and one must be rejected with conflict
    assert sorted(results) == ["CONFLICT", "SUCCESS"]

    # Verify authoritative database state
    async with session_factory() as verify_session:
        verify_service = GateService(verify_session)
        final_gate = await verify_service.get_gate(principal=principal, gate_id=gate_id)
        assert final_gate.state == GateState.APPROVED.value
        decisions = await verify_service.list_gate_decisions(principal=principal, gate_id=gate_id)
        assert len(decisions) == 1
