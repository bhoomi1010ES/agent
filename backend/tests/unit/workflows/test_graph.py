"""Unit tests for LangGraph workflow graph assembly, compilation, and thread configuration."""

import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.workflows.graph import (
    build_modernization_workflow_graph,
    compile_workflow_graph,
    get_workflow_thread_config,
    should_continue,
)
from modernization_platform.workflows.state import create_initial_workflow_state


def test_build_modernization_workflow_graph() -> None:
    """StateGraph compiles with all expected lifecycle nodes and gates."""
    builder = build_modernization_workflow_graph()
    assert "initialize" in builder.nodes
    assert "intake" in builder.nodes
    assert "gate_g1" in builder.nodes
    assert "analysis" in builder.nodes
    assert "gate_g2" in builder.nodes
    assert "architecture" in builder.nodes
    assert "gate_g3" in builder.nodes
    assert "conversion" in builder.nodes
    assert "verification" in builder.nodes
    assert "gate_g4" in builder.nodes
    assert "completion" in builder.nodes


def test_compile_workflow_graph() -> None:
    """compile_workflow_graph returns a CompiledStateGraph bound to checkpointer."""
    checkpointer = InMemorySaver()
    compiled = compile_workflow_graph(checkpointer=checkpointer)
    assert isinstance(compiled, CompiledStateGraph)
    assert compiled.checkpointer is checkpointer


def test_get_workflow_thread_config_uses_stable_job_id() -> None:
    """get_workflow_thread_config returns stable thread_id bound to the job ID."""
    job_id = uuid.uuid4()
    config = get_workflow_thread_config(job_id)
    assert config["configurable"]["thread_id"] == str(job_id)

    # String job ID also works
    config_str = get_workflow_thread_config(str(job_id))
    assert config_str["configurable"]["thread_id"] == str(job_id)


def test_should_continue_router() -> None:
    """should_continue correctly directs active vs failed workflow branches."""
    running_state = create_initial_workflow_state(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        owner="test-owner",
    )
    running_state["status"] = JobLifecycleState.RUNNING.value
    assert should_continue(running_state) == "continue"

    failed_state = dict(running_state)
    failed_state["status"] = JobLifecycleState.FAILED.value
    assert should_continue(failed_state) == "end"  # type: ignore[arg-type]

    cancelled_state = dict(running_state)
    cancelled_state["status"] = JobLifecycleState.CANCELLED.value
    assert should_continue(cancelled_state) == "end"  # type: ignore[arg-type]
