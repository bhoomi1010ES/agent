"""Unit tests for WorkflowEngine execution, interrupt handling, and gate resumption."""

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.workflows.engine import WorkflowEngine


@pytest.mark.asyncio
async def test_workflow_engine_execution_halts_at_gate_g1() -> None:
    """Starting workflow executes until first unapproved gate and enters awaiting_approval."""
    checkpointer = InMemorySaver()
    engine = WorkflowEngine(checkpointer=checkpointer)

    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    owner = "lead@example.com"

    state = await engine.start_workflow(
        job_id=job_id,
        tenant_id=tenant_id,
        owner=owner,
    )

    assert state["job_id"] == str(job_id)
    assert state["status"] == JobLifecycleState.AWAITING_APPROVAL.value
    assert state["needs_human"] is True
    assert state["current_gate"] == "G1_FEASIBILITY"
    assert "initialized" in state["completed_steps"]
    assert "intake" in state["completed_steps"]

    # Verify checkpoint persistence in engine
    checkpoint = await engine.get_state(job_id)
    assert checkpoint is not None
    assert checkpoint["job_id"] == str(job_id)


@pytest.mark.asyncio
async def test_workflow_engine_sequential_gate_resumption_to_completion() -> None:
    """WorkflowEngine sequentially halts and resumes through G1-G4 until completion."""
    checkpointer = InMemorySaver()
    engine = WorkflowEngine(checkpointer=checkpointer)

    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # 1. Start: reaches G1
    s1 = await engine.start_workflow(job_id=job_id, tenant_id=tenant_id, owner="dev")
    assert s1["current_gate"] == "G1_FEASIBILITY"

    # 2. Resume G1 with approval: reaches G2
    s2 = await engine.resume_workflow(
        job_id=job_id,
        resume_payload={"decision": "approved", "actor": "tech_lead_1"},
    )
    assert s2["current_gate"] == "G2_CHARACTERIZATION"
    assert "G1_FEASIBILITY" in s2["gate_approvals"]
    assert "analysis" in s2["completed_steps"]

    # 3. Resume G2 with approval: reaches G3
    s3 = await engine.resume_workflow(
        job_id=job_id,
        resume_payload={"decision": "approved", "actor": "tech_lead_2"},
    )
    assert s3["current_gate"] == "G3_BLUEPRINT_PLAN"
    assert "G2_CHARACTERIZATION" in s3["gate_approvals"]
    assert "architecture" in s3["completed_steps"]

    # 4. Resume G3 with approval: reaches G4
    s4 = await engine.resume_workflow(
        job_id=job_id,
        resume_payload={"decision": "approved", "actor": "tech_lead_3"},
    )
    assert s4["current_gate"] == "G4_INTEGRATION_PR"
    assert "G3_BLUEPRINT_PLAN" in s4["gate_approvals"]
    assert "conversion" in s4["completed_steps"]
    assert "verification" in s4["completed_steps"]

    # 5. Resume G4 with approval: finishes at completion
    s5 = await engine.resume_workflow(
        job_id=job_id,
        resume_payload={"decision": "approved", "actor": "release_manager"},
    )
    assert s5["status"] == JobLifecycleState.COMPLETED.value
    assert s5["current_step"] == "completed"
    assert s5["needs_human"] is False
    assert "completed" in s5["completed_steps"]


@pytest.mark.asyncio
async def test_workflow_engine_rejection_at_gate_terminates_workflow() -> None:
    """When a gate decision is rejected, workflow transitions to terminal failed state."""
    checkpointer = InMemorySaver()
    engine = WorkflowEngine(checkpointer=checkpointer)

    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # Reach G1
    await engine.start_workflow(job_id=job_id, tenant_id=tenant_id, owner="dev")

    # Reject at G1
    result = await engine.resume_workflow(
        job_id=job_id,
        resume_payload={
            "decision": "rejected",
            "actor": "governance_board",
            "feedback": "Architecture fails compliance guidelines.",
        },
    )

    assert result["status"] == JobLifecycleState.FAILED.value
    assert result["failure_classification"] == "terminal"
    assert result["failure_reason"] is not None
    assert "compliance" in result["failure_reason"].lower()
    assert result["needs_human"] is False
