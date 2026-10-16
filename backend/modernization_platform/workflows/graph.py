"""StateGraph definition, compilation with durable checkpointer, and thread configuration."""

import logging
import uuid
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.workflows.nodes import (
    analysis_node,
    architecture_node,
    completion_node,
    conversion_node,
    initialize_node,
    intake_node,
    make_gate_node,
    verification_node,
)
from modernization_platform.workflows.state import ModernizationWorkflowState

logger = logging.getLogger(__name__)


@log_errors
def should_continue(state: ModernizationWorkflowState) -> str:
    """Evaluate whether workflow should continue to the next phase or terminate on failure."""
    try:
        status = state.get("status")
        if status in (JobLifecycleState.FAILED.value, JobLifecycleState.CANCELLED.value):
            return "end"
        return "continue"
    except Exception as exc:
        logger.exception("should_continue failed | %s: %s", type(exc).__name__, exc)
        return "end"


@log_errors
def route_gate_g1(state: ModernizationWorkflowState) -> str:
    """Route Gate 1: continue to analysis, return to intake on rejection, or end on failure."""
    try:
        status = state.get("status")
        if status in (JobLifecycleState.FAILED.value, JobLifecycleState.CANCELLED.value):
            return "end"
        if state.get("current_step") == "intake":
            return "intake"
        return "continue"
    except Exception as exc:
        logger.exception("route_gate_g1 failed | %s: %s", type(exc).__name__, exc)
        return "end"


@log_errors
def route_gate_g2(state: ModernizationWorkflowState) -> str:
    """Route Gate 2: continue to architecture, return to analysis on rejection, or end on failure."""
    try:
        status = state.get("status")
        if status in (JobLifecycleState.FAILED.value, JobLifecycleState.CANCELLED.value):
            return "end"
        if state.get("current_step") == "analysis":
            return "analysis"
        return "continue"
    except Exception as exc:
        logger.exception("route_gate_g2 failed | %s: %s", type(exc).__name__, exc)
        return "end"


@log_errors
def route_gate_g3(state: ModernizationWorkflowState) -> str:
    """Route Gate 3: continue to conversion, return to architecture on rejection, or end on failure."""
    try:
        status = state.get("status")
        if status in (JobLifecycleState.FAILED.value, JobLifecycleState.CANCELLED.value):
            return "end"
        if state.get("current_step") == "architecture":
            return "architecture"
        return "continue"
    except Exception as exc:
        logger.exception("route_gate_g3 failed | %s: %s", type(exc).__name__, exc)
        return "end"


@log_errors
def route_gate_g4(state: ModernizationWorkflowState) -> str:
    """Route Gate 4: continue to completion, return to conversion on rejection, or end on failure."""
    try:
        status = state.get("status")
        if status in (JobLifecycleState.FAILED.value, JobLifecycleState.CANCELLED.value):
            return "end"
        if state.get("current_step") == "conversion":
            return "conversion"
        return "continue"
    except Exception as exc:
        logger.exception("route_gate_g4 failed | %s: %s", type(exc).__name__, exc)
        return "end"


@log_errors
def build_modernization_workflow_graph() -> StateGraph[Any, Any, Any, Any]:
    """Assemble the StateGraph linking stages, idempotent node boundaries, and approval gates."""
    try:
        builder: StateGraph[Any, Any, Any, Any] = StateGraph(ModernizationWorkflowState)

        # 1. Register operational phase nodes
        builder.add_node("initialize", initialize_node)
        builder.add_node("intake", intake_node)
        builder.add_node("gate_g1", cast(Any, make_gate_node("G1_FEASIBILITY", "analysis")))
        builder.add_node("analysis", analysis_node)
        builder.add_node(
            "gate_g2", cast(Any, make_gate_node("G2_CHARACTERIZATION", "architecture"))
        )
        builder.add_node("architecture", architecture_node)
        builder.add_node("gate_g3", cast(Any, make_gate_node("G3_BLUEPRINT_PLAN", "conversion")))
        builder.add_node("conversion", conversion_node)
        builder.add_node("verification", verification_node)
        builder.add_node("gate_g4", cast(Any, make_gate_node("G4_INTEGRATION_PR", "completed")))
        builder.add_node("completion", completion_node)

        # 2. Add sequential and conditional transitions
        builder.add_edge(START, "initialize")
        builder.add_edge("initialize", "intake")
        builder.add_edge("intake", "gate_g1")

        builder.add_conditional_edges(
            "gate_g1",
            route_gate_g1,
            {"continue": "analysis", "intake": "intake", "end": END},
        )
        builder.add_edge("analysis", "gate_g2")

        builder.add_conditional_edges(
            "gate_g2",
            route_gate_g2,
            {"continue": "architecture", "analysis": "analysis", "end": END},
        )
        builder.add_edge("architecture", "gate_g3")

        builder.add_conditional_edges(
            "gate_g3",
            route_gate_g3,
            {"continue": "conversion", "architecture": "architecture", "end": END},
        )
        builder.add_edge("conversion", "verification")
        builder.add_edge("verification", "gate_g4")

        builder.add_conditional_edges(
            "gate_g4",
            route_gate_g4,
            {"continue": "completion", "conversion": "conversion", "end": END},
        )
        builder.add_edge("completion", END)

        return builder
    except Exception as exc:
        logger.exception(
            "build_modernization_workflow_graph failed | %s: %s", type(exc).__name__, exc
        )
        raise


@log_errors
def compile_workflow_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the modernization StateGraph bound to the designated checkpointer."""
    try:
        builder = build_modernization_workflow_graph()
        compiled = builder.compile(checkpointer=checkpointer)
        return compiled
    except Exception as exc:
        logger.exception("compile_workflow_graph failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def get_workflow_thread_config(job_id: uuid.UUID | str) -> RunnableConfig:
    """Derive the deterministic LangGraph configuration with thread_id equal to the stable job ID."""
    try:
        return {"configurable": {"thread_id": str(job_id)}}
    except Exception as exc:
        logger.exception("get_workflow_thread_config failed | %s: %s", type(exc).__name__, exc)
        raise


__all__ = [
    "build_modernization_workflow_graph",
    "compile_workflow_graph",
    "get_workflow_thread_config",
    "should_continue",
]
