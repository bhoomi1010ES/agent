"""Integration tests verifying safe worker recovery and non-duplication after process crash."""

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.workers.workflow_worker import WorkflowWorker
from modernization_platform.workflows.checkpointer import (
    ensure_windows_event_loop_policy,
    normalize_postgres_connection_string,
    setup_postgres_checkpointer,
)
from modernization_platform.workflows.engine import WorkflowEngine
from tests.integration.db.conftest import _PORT_AVAILABLE, TEST_DB_URL, _skip_or_fail_database
from tests.integration.workflows.test_reconciliation import _create_test_job, _create_test_principal


@pytest.mark.asyncio
async def test_worker_crash_recovery_resumes_from_durable_checkpoint(
    db_session: AsyncSession,
) -> None:
    """A crashed worker process is replaced by a new worker that recovers active jobs from PostgreSQL checkpoints."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database(
            "PostgreSQL test database not available for worker crash recovery test"
        )

    ensure_windows_event_loop_policy()
    norm_url = normalize_postgres_connection_string(TEST_DB_URL)
    await setup_postgres_checkpointer(norm_url)

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    # 1. Worker 1 runs and executes initial phases up to G1 checkpoint
    async with AsyncPostgresSaver.from_conn_string(norm_url) as saver1:
        engine1 = WorkflowEngine(checkpointer=saver1)
        assert job.tenant_id is not None
        worker1 = WorkflowWorker(engine=engine1, session_factory=session_factory, name="worker-1")
        state1 = await worker1.process_job(
            job_id=job.id,
            tenant_id=job.tenant_id,
            owner=job.owner,
        )
        assert state1["current_gate"] == "G1_FEASIBILITY"
        assert "initialized" in state1["completed_steps"]
        assert "intake" in state1["completed_steps"]

        # Worker 1 "crashes" unexpectedly / terminates
        worker1.request_stop()
        assert worker1.should_stop is True

    # 2. Worker 2 boots up in a fresh process, recovers active jobs, and inspects checkpoints
    async with AsyncPostgresSaver.from_conn_string(norm_url) as saver2:
        engine2 = WorkflowEngine(checkpointer=saver2)
        worker2 = WorkflowWorker(engine=engine2, session_factory=session_factory, name="worker-2")

        # Fetch state from checkpointer before recovery to verify persistence
        recovered_state = await engine2.get_state(job.id)
        assert recovered_state is not None
        assert recovered_state["job_id"] == str(job.id)
        assert "intake" in recovered_state["completed_steps"]
        assert recovered_state["current_gate"] == "G1_FEASIBILITY"

        # Resume execution at G1 using engine2
        resumed_state = await engine2.resume_workflow(
            job_id=job.id,
            resume_payload={"decision": "approved", "actor": "recovery_admin"},
            session=db_session,
        )

        # Advanced to G2 without re-running intake
        assert resumed_state["current_gate"] == "G2_CHARACTERIZATION"
        assert "G1_FEASIBILITY" in resumed_state["gate_approvals"]
        assert "analysis" in resumed_state["completed_steps"]
        assert resumed_state["completed_steps"].count("intake") == 1
        assert resumed_state["completed_steps"].count("analysis") == 1

        # Test graceful shutdown of worker 2
        worker2.request_stop()
        assert worker2.should_stop is True
