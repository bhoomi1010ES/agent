"""Workflow nodes implementing phase execution, approval gate interrupts, and idempotency boundaries."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.workflows.state import (
    ModernizationWorkflowState,
    is_step_completed,
    mark_step_completed,
)

logger = logging.getLogger(__name__)


@log_errors
def initialize_node(state: ModernizationWorkflowState) -> dict[str, Any]:
    """Initialize workflow execution, validate baseline state, and establish idempotency tracker."""
    try:
        step_name = "initialized"
        completed = list(state.get("completed_steps", []))
        if step_name not in completed:
            completed.append(step_name)

        return {
            "status": JobLifecycleState.RUNNING.value,
            "current_step": step_name,
            "completed_steps": completed,
            "iteration_count": state.get("iteration_count", 0) + 1,
            "needs_human": False,
            "current_gate": None,
        }
    except Exception as exc:
        logger.exception("initialize_node failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def intake_node(state: ModernizationWorkflowState) -> dict[str, Any]:
    """Execute source intake stage within an idempotent boundary."""
    try:
        step_name = "intake"
        completed = list(state.get("completed_steps", []))
        if not is_step_completed(state, step_name):
            logger.info("Executing intake phase for job %s", state["job_id"])
            completed = mark_step_completed(state, step_name)

        return {
            "current_step": step_name,
            "completed_steps": completed,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    except Exception as exc:
        logger.exception("intake_node failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def analysis_node(state: ModernizationWorkflowState) -> dict[str, Any]:
    """Execute legacy analysis stage within an idempotent boundary."""
    try:
        step_name = "analysis"
        completed = list(state.get("completed_steps", []))
        if not is_step_completed(state, step_name):
            logger.info("Executing analysis phase for job %s", state["job_id"])
            completed = mark_step_completed(state, step_name)

        return {
            "current_step": step_name,
            "completed_steps": completed,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    except Exception as exc:
        logger.exception("analysis_node failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def architecture_node(state: ModernizationWorkflowState) -> dict[str, Any]:
    """Execute architecture blueprinting stage within an idempotent boundary."""
    try:
        step_name = "architecture"
        completed = list(state.get("completed_steps", []))
        if not is_step_completed(state, step_name):
            logger.info("Executing architecture phase for job %s", state["job_id"])
            completed = mark_step_completed(state, step_name)

        return {
            "current_step": step_name,
            "completed_steps": completed,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    except Exception as exc:
        logger.exception("architecture_node failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def conversion_node(state: ModernizationWorkflowState) -> dict[str, Any]:
    """Execute code conversion stage within an idempotent boundary."""
    try:
        step_name = "conversion"
        completed = list(state.get("completed_steps", []))
        if not is_step_completed(state, step_name):
            logger.info("Executing conversion phase for job %s", state["job_id"])
            completed = mark_step_completed(state, step_name)

        return {
            "current_step": step_name,
            "completed_steps": completed,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    except Exception as exc:
        logger.exception("conversion_node failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def verification_node(state: ModernizationWorkflowState) -> dict[str, Any]:
    """Execute equivalence and verification stage within an idempotent boundary."""
    try:
        step_name = "verification"
        completed = list(state.get("completed_steps", []))
        if not is_step_completed(state, step_name):
            logger.info("Executing verification phase for job %s", state["job_id"])
            completed = mark_step_completed(state, step_name)

        return {
            "current_step": step_name,
            "completed_steps": completed,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    except Exception as exc:
        logger.exception("verification_node failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def make_gate_node(
    gate_type: str, next_phase: str
) -> Callable[[ModernizationWorkflowState], dict[str, Any]]:
    """Construct an interruptible gate node for approval gates G1-G4."""
    try:

        @log_errors
        def gate_node(state: ModernizationWorkflowState) -> dict[str, Any]:
            try:
                approvals = dict(state.get("gate_approvals", {}))
                completed = list(state.get("completed_steps", []))

                # If this gate has not been decided yet, interrupt execution
                if gate_type not in approvals:
                    logger.info(
                        "Workflow pausing at gate %s for job %s; awaiting human approval",
                        gate_type,
                        state["job_id"],
                    )
                    interrupt_payload = {
                        "gate_type": gate_type,
                        "job_id": state["job_id"],
                        "needs_human": True,
                        "artifact_references": state.get("artifact_references", {}),
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    # LangGraph dynamic interrupt halts execution here and returns value
                    decision_input = interrupt(interrupt_payload)

                    # Resumed execution receives decision_input
                    if not isinstance(decision_input, dict):
                        decision_input = {"decision": str(decision_input), "actor": "system"}

                    decision = decision_input.get("decision", "rejected")
                    actor = decision_input.get("actor", "human")
                    feedback = decision_input.get("feedback")
                    waivers = decision_input.get("waivers")

                    return_to_stage = decision_input.get("return_to_stage", False)
                    rejection_target = decision_input.get("rejection_target")

                    if decision == "rejected":
                        logger.warning(
                            "Gate %s rejected for job %s by %s", gate_type, state["job_id"], actor
                        )
                        if return_to_stage or rejection_target:
                            from modernization_platform.domain.gates.rejection import (
                                get_rejection_target_stage,
                            )

                            target_stage = rejection_target or get_rejection_target_stage(gate_type)
                            logger.info(
                                "Routing rejected gate %s for job %s back to stage %s",
                                gate_type,
                                state["job_id"],
                                target_stage,
                            )
                            completed = [
                                s
                                for s in state.get("completed_steps", [])
                                if s != target_stage
                                and not s.startswith(f"gate_{gate_type.lower()}")
                            ]
                            rejections = list(state.get("rejection_history", []))
                            rejections.append(
                                {
                                    "gate_type": gate_type,
                                    "actor": actor,
                                    "feedback": feedback,
                                    "target_stage": target_stage,
                                    "timestamp": datetime.now(UTC).isoformat(),
                                }
                            )
                            return {
                                "status": JobLifecycleState.RUNNING.value,
                                "current_step": target_stage,
                                "completed_steps": completed,
                                "rejection_history": rejections,
                                "needs_human": False,
                                "current_gate": None,
                                "failure_reason": None,
                                "failure_classification": None,
                                "iteration_count": state.get("iteration_count", 0) + 1,
                            }
                        return {
                            "status": JobLifecycleState.FAILED.value,
                            "current_step": f"gate_{gate_type.lower()}_rejected",
                            "failure_reason": f"Approval gate {gate_type} rejected: {feedback or 'No feedback provided'}",
                            "failure_classification": "terminal",
                            "needs_human": False,
                            "current_gate": None,
                        }

                    approvals[gate_type] = {
                        "gate_type": gate_type,
                        "decision": decision,
                        "actor": actor,
                        "feedback": feedback,
                        "waivers": waivers,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    completed = mark_step_completed(state, f"gate_{gate_type.lower()}")

                return {
                    "status": JobLifecycleState.RUNNING.value,
                    "current_step": next_phase,
                    "completed_steps": completed,
                    "gate_approvals": approvals,
                    "needs_human": False,
                    "current_gate": None,
                    "iteration_count": state.get("iteration_count", 0) + 1,
                }
            except GraphInterrupt:
                raise
            except Exception as exc:
                logger.exception(
                    "gate_node (%s) failed | %s: %s", gate_type, type(exc).__name__, exc
                )
                raise

        return gate_node
    except Exception as exc:
        logger.exception("make_gate_node failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def pause_node(state: ModernizationWorkflowState) -> dict[str, Any]:
    """Explicitly pause the workflow state."""
    try:
        return {
            "status": JobLifecycleState.PAUSED.value,
            "current_step": "paused",
            "needs_human": False,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    except Exception as exc:
        logger.exception("pause_node failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def resume_node(state: ModernizationWorkflowState) -> dict[str, Any]:
    """Resume execution from paused state back to running."""
    try:
        return {
            "status": JobLifecycleState.RUNNING.value,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    except Exception as exc:
        logger.exception("resume_node failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def completion_node(state: ModernizationWorkflowState) -> dict[str, Any]:
    """Finalize workflow execution, verify prerequisites, and mark job as completed."""
    try:
        step_name = "completed"
        completed = mark_step_completed(state, step_name)
        return {
            "status": JobLifecycleState.COMPLETED.value,
            "current_step": step_name,
            "completed_steps": completed,
            "needs_human": False,
            "current_gate": None,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    except Exception as exc:
        logger.exception("completion_node failed | %s: %s", type(exc).__name__, exc)
        raise


__all__ = [
    "analysis_node",
    "architecture_node",
    "completion_node",
    "conversion_node",
    "initialize_node",
    "intake_node",
    "make_gate_node",
    "pause_node",
    "resume_node",
    "verification_node",
]
