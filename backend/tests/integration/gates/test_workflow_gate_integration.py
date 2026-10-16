"""Workflow integration tests verifying LangGraph interrupt, approval resume, and rejection return."""

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.workflows.engine import WorkflowEngine


@pytest.mark.asyncio
async def test_workflow_gate_g1_interrupt_and_approval_resume() -> None:
    """Workflow execution halts at G1 approval gate and resumes to analysis upon approval."""
    checkpointer = InMemorySaver()
    engine = WorkflowEngine(checkpointer=checkpointer)

    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # 1. Start workflow: executes initialize -> intake -> halts at gate_g1
    s1 = await engine.start_workflow(
        job_id=job_id,
        tenant_id=tenant_id,
        owner="architect",
    )
    assert s1["needs_human"] is True
    assert s1["current_gate"] == "G1_FEASIBILITY"
    assert s1["status"] == JobLifecycleState.AWAITING_APPROVAL.value
    assert "intake" in s1["completed_steps"]
    assert "gate_g1" not in s1.get("gate_approvals", {})

    # 2. Resume G1 with approval: continues to analysis and pauses at gate_g2
    s2 = await engine.resume_workflow(
        job_id=job_id,
        resume_payload={
            "decision": "approved",
            "actor": "lead-approver",
            "feedback": "Feasibility verified.",
        },
    )
    assert s2["needs_human"] is True
    assert s2["current_gate"] == "G2_CHARACTERIZATION"
    assert "analysis" in s2["completed_steps"]
    assert "G1_FEASIBILITY" in s2["gate_approvals"]
    assert s2["gate_approvals"]["G1_FEASIBILITY"]["decision"] == "approved"


@pytest.mark.asyncio
async def test_workflow_gate_rejection_returns_to_designated_stage() -> None:
    """When a gate decision is rejected with return_to_stage=True, workflow loops back to designated stage."""
    checkpointer = InMemorySaver()
    engine = WorkflowEngine(checkpointer=checkpointer)

    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # Reach G1
    await engine.start_workflow(job_id=job_id, tenant_id=tenant_id, owner="architect")

    # Approve G1 -> reaches G2
    s2 = await engine.resume_workflow(
        job_id=job_id,
        resume_payload={"decision": "approved", "actor": "approver_1"},
    )
    assert s2["current_gate"] == "G2_CHARACTERIZATION"

    # Reject at G2 with return_to_stage=True -> returns to analysis, clears G2 from gate_approvals
    s3 = await engine.resume_workflow(
        job_id=job_id,
        resume_payload={
            "decision": "rejected",
            "actor": "qa_lead",
            "feedback": "Characterization incomplete for database dependencies.",
            "return_to_stage": True,
            "rejection_target": "analysis",
        },
    )

    # Workflow has returned to analysis and re-reached gate_g2!
    assert s3["needs_human"] is True
    assert s3["current_gate"] == "G2_CHARACTERIZATION"
    assert "G2_CHARACTERIZATION" not in s3.get("gate_approvals", {})
    # Rejection history recorded
    assert "rejection_history" in s3
    assert len(s3["rejection_history"]) == 1
    assert s3["rejection_history"][0]["gate_type"] == "G2_CHARACTERIZATION"
    assert "database dependencies" in s3["rejection_history"][0]["feedback"]

    # Now approve G2: advances forward to architecture -> halts at G3
    s4 = await engine.resume_workflow(
        job_id=job_id,
        resume_payload={"decision": "approved", "actor": "qa_lead", "feedback": "Resolved."},
    )
    assert s4["needs_human"] is True
    assert s4["current_gate"] == "G3_BLUEPRINT_PLAN"
    assert "architecture" in s4["completed_steps"]


@pytest.mark.asyncio
async def test_worker_crash_simulation_at_gate_survives_restart() -> None:
    """Simulate worker process crash while gate is pending; new engine resumes from durable checkpoint."""
    shared_checkpointer = InMemorySaver()
    engine_1 = WorkflowEngine(checkpointer=shared_checkpointer)

    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # Worker 1 starts workflow, interrupts at G1
    s1 = await engine_1.start_workflow(job_id=job_id, tenant_id=tenant_id, owner="dev")
    assert s1["needs_human"] is True
    assert s1["current_gate"] == "G1_FEASIBILITY"

    # Worker 1 crashes / terminates (engine_1 discarded)
    del engine_1

    # Worker 2 boots up with the durable checkpointer
    engine_2 = WorkflowEngine(checkpointer=shared_checkpointer)

    # Worker 2 resumes from durable checkpoint
    s2 = await engine_2.resume_workflow(
        job_id=job_id,
        resume_payload={"decision": "approved", "actor": "director"},
    )
    assert s2["needs_human"] is True
    assert s2["current_gate"] == "G2_CHARACTERIZATION"
    assert "analysis" in s2["completed_steps"]
    assert "G1_FEASIBILITY" in s2["gate_approvals"]
