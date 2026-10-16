"""Unit tests verifying that workflow resumption does not duplicate completed side effects."""

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from modernization_platform.workflows.graph import get_workflow_thread_config
from modernization_platform.workflows.state import (
    ModernizationWorkflowState,
    create_initial_workflow_state,
    is_step_completed,
    mark_step_completed,
)


@pytest.mark.asyncio
async def test_resumed_nodes_do_not_duplicate_side_effects() -> None:
    """Execution resumes strictly from uncompleted steps without re-executing prior nodes."""
    side_effect_counts = {"step_a": 0, "step_b": 0, "step_c": 0}

    def node_a(state: ModernizationWorkflowState) -> dict[str, object]:
        if not is_step_completed(state, "step_a"):
            side_effect_counts["step_a"] += 1
            completed = mark_step_completed(state, "step_a")
            return {"completed_steps": completed, "current_step": "step_a"}
        return {}

    def gate_interrupt(state: ModernizationWorkflowState) -> dict[str, object]:
        decision = interrupt("Approve before step B")
        return {
            "current_step": "gate_approved",
            "metadata": {"decision": decision},
        }

    def node_b(state: ModernizationWorkflowState) -> dict[str, object]:
        if not is_step_completed(state, "step_b"):
            side_effect_counts["step_b"] += 1
            completed = mark_step_completed(state, "step_b")
            return {"completed_steps": completed, "current_step": "step_b"}
        return {}

    builder = StateGraph(ModernizationWorkflowState)
    builder.add_node("node_a", node_a)
    builder.add_node("gate", gate_interrupt)
    builder.add_node("node_b", node_b)
    builder.add_edge(START, "node_a")
    builder.add_edge("node_a", "gate")
    builder.add_edge("gate", "node_b")
    builder.add_edge("node_b", END)

    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    job_id = uuid.uuid4()
    config = get_workflow_thread_config(job_id)

    initial_state = create_initial_workflow_state(
        job_id=job_id,
        tenant_id=uuid.uuid4(),
        owner="test-owner",
    )

    # First execution run: executes A and halts at gate
    await graph.ainvoke(initial_state, config=config)

    assert side_effect_counts["step_a"] == 1
    assert side_effect_counts["step_b"] == 0

    # Resume execution with Command(resume=...)
    from langgraph.types import Command

    await graph.ainvoke(Command(resume="approved"), config=config)

    # Step A was NOT re-executed upon resumption
    assert side_effect_counts["step_a"] == 1
    # Step B executed exactly once
    assert side_effect_counts["step_b"] == 1

    # Fetch checkpoint state
    final_state = await graph.aget_state(config)
    assert "step_a" in final_state.values["completed_steps"]
    assert "step_b" in final_state.values["completed_steps"]
