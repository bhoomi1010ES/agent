"""Unit tests for workflow node logic, gate interrupt mechanics, and idempotency boundaries."""

import uuid
from unittest.mock import patch

from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.workflows.nodes import (
    analysis_node,
    architecture_node,
    completion_node,
    conversion_node,
    initialize_node,
    intake_node,
    make_gate_node,
    pause_node,
    resume_node,
    verification_node,
)
from modernization_platform.workflows.state import create_initial_workflow_state


def test_initialize_node_advances_to_running() -> None:
    """initialize_node marks status as running and tracks initialized step."""
    state = create_initial_workflow_state(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        owner="test-owner",
    )
    result = initialize_node(state)
    assert result["status"] == JobLifecycleState.RUNNING.value
    assert result["current_step"] == "initialized"
    assert "initialized" in result["completed_steps"]


def test_phase_nodes_execute_within_idempotency_boundaries() -> None:
    """Phase nodes record step completion and do not duplicate when already completed."""
    state = create_initial_workflow_state(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        owner="test-owner",
    )

    # First run: intake
    res1 = intake_node(state)
    assert res1["current_step"] == "intake"
    assert "intake" in res1["completed_steps"]

    # Second run: intake with completed_steps already containing intake
    state["completed_steps"] = ["intake"]
    res2 = intake_node(state)
    assert res2["completed_steps"] == ["intake"]

    # Analysis node
    res_analysis = analysis_node(state)
    assert res_analysis["current_step"] == "analysis"
    assert "analysis" in res_analysis["completed_steps"]

    # Architecture node
    res_arch = architecture_node(state)
    assert res_arch["current_step"] == "architecture"
    assert "architecture" in res_arch["completed_steps"]

    # Conversion node
    res_conv = conversion_node(state)
    assert res_conv["current_step"] == "conversion"
    assert "conversion" in res_conv["completed_steps"]

    # Verification node
    res_ver = verification_node(state)
    assert res_ver["current_step"] == "verification"
    assert "verification" in res_ver["completed_steps"]


def test_gate_node_triggers_interrupt_when_pending() -> None:
    """Gate node triggers LangGraph interrupt when approval has not been granted."""
    state = create_initial_workflow_state(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        owner="test-owner",
    )
    gate_fn = make_gate_node("G1_FEASIBILITY", next_phase="analysis")

    with patch("modernization_platform.workflows.nodes.interrupt") as mock_interrupt:
        mock_interrupt.return_value = {"decision": "approved", "actor": "tech_lead"}
        res = gate_fn(state)

        mock_interrupt.assert_called_once()
        call_arg = mock_interrupt.call_args[0][0]
        assert call_arg["gate_type"] == "G1_FEASIBILITY"
        assert call_arg["needs_human"] is True

        assert res["status"] == JobLifecycleState.RUNNING.value
        assert res["current_step"] == "analysis"
        assert "G1_FEASIBILITY" in res["gate_approvals"]
        assert res["gate_approvals"]["G1_FEASIBILITY"]["decision"] == "approved"
        assert "gate_g1_feasibility" in res["completed_steps"]


def test_gate_node_handles_rejection_with_failure() -> None:
    """Gate node transitions workflow to failed when decision is rejected."""
    state = create_initial_workflow_state(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        owner="test-owner",
    )
    gate_fn = make_gate_node("G2_CHARACTERIZATION", next_phase="architecture")

    with patch("modernization_platform.workflows.nodes.interrupt") as mock_interrupt:
        mock_interrupt.return_value = {
            "decision": "rejected",
            "actor": "security_officer",
            "feedback": "Legacy dependencies do not satisfy security baselines.",
        }
        res = gate_fn(state)

        assert res["status"] == JobLifecycleState.FAILED.value
        assert res["failure_classification"] == "terminal"
        assert "rejected" in res["failure_reason"].lower()


def test_pause_resume_and_completion_nodes() -> None:
    """Pause, resume, and completion nodes correctly mutate status states."""
    state = create_initial_workflow_state(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        owner="test-owner",
    )

    paused = pause_node(state)
    assert paused["status"] == JobLifecycleState.PAUSED.value
    assert paused["current_step"] == "paused"

    resumed = resume_node(state)
    assert resumed["status"] == JobLifecycleState.RUNNING.value

    completed = completion_node(state)
    assert completed["status"] == JobLifecycleState.COMPLETED.value
    assert completed["current_step"] == "completed"
    assert "completed" in completed["completed_steps"]
