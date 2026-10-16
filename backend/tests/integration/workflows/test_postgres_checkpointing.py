"""Integration tests for durable LangGraph execution with PostgreSQL checkpointer."""

import uuid

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.workflows.checkpointer import (
    ensure_windows_event_loop_policy,
    normalize_postgres_connection_string,
    setup_postgres_checkpointer,
)
from modernization_platform.workflows.engine import WorkflowEngine
from tests.integration.db.conftest import _PORT_AVAILABLE, TEST_DB_URL, _skip_or_fail_database


@pytest.mark.asyncio
async def test_postgres_durable_checkpoint_lifecycle(db_session: AsyncSession) -> None:
    """Verify durable checkpoints are saved in PostgreSQL and workflows resume across thread_id."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available for checkpointer test")

    ensure_windows_event_loop_policy()
    norm_url = normalize_postgres_connection_string(TEST_DB_URL)

    # 1. Setup checkpoint tables in PostgreSQL
    await setup_postgres_checkpointer(norm_url)

    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # 2. Run workflow using AsyncPostgresSaver
    async with AsyncPostgresSaver.from_conn_string(norm_url) as saver:
        engine = WorkflowEngine(checkpointer=saver)

        # Start workflow: halts at G1
        state1 = await engine.start_workflow(
            job_id=job_id,
            tenant_id=tenant_id,
            owner="integration-test",
        )

        assert state1["job_id"] == str(job_id)
        assert state1["current_gate"] == "G1_FEASIBILITY"
        assert state1["needs_human"] is True
        assert state1["status"] == JobLifecycleState.AWAITING_APPROVAL.value

        # 3. Verify directly in PostgreSQL that checkpoints table has a row for this thread_id
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM checkpoints WHERE thread_id = :tid"),
            {"tid": str(job_id)},
        )
        checkpoint_count = result.scalar() or 0
        assert checkpoint_count > 0

    # 4. In a new checkpointer connection / engine session, resume the workflow using the same job_id thread
    async with AsyncPostgresSaver.from_conn_string(norm_url) as resumed_saver:
        resumed_engine = WorkflowEngine(checkpointer=resumed_saver)

        # Resume G1
        state2 = await resumed_engine.resume_workflow(
            job_id=job_id,
            resume_payload={"decision": "approved", "actor": "tech_lead"},
        )

        assert state2["current_gate"] == "G2_CHARACTERIZATION"
        assert "G1_FEASIBILITY" in state2["gate_approvals"]

        # Resume remaining gates until completion
        await resumed_engine.resume_workflow(
            job_id=job_id,
            resume_payload={"decision": "approved", "actor": "tech_lead"},
        )
        await resumed_engine.resume_workflow(
            job_id=job_id,
            resume_payload={"decision": "approved", "actor": "tech_lead"},
        )
        final_state = await resumed_engine.resume_workflow(
            job_id=job_id,
            resume_payload={"decision": "approved", "actor": "tech_lead"},
        )

        assert final_state["status"] == JobLifecycleState.COMPLETED.value
        assert final_state["current_step"] == "completed"

        # Verify state retrieval from durable checkpoint
        persisted_state = await resumed_engine.get_state(job_id)
        assert persisted_state is not None
        assert persisted_state["status"] == JobLifecycleState.COMPLETED.value
