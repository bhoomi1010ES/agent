"""Typed workflow state contracts and boundary helpers for LangGraph modernization orchestration."""

import logging
import uuid
from typing import Any, NotRequired, TypedDict

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.jobs.states import JobLifecycleState

logger = logging.getLogger(__name__)


class ArtifactReferenceDict(TypedDict):
    """Lightweight metadata reference to an artifact stored in object storage."""

    artifact_id: str
    artifact_type: str
    storage_ref: str
    content_hash: str
    size_bytes: int | None
    content_type: str | None


class GateDecisionRecord(TypedDict):
    """Record of a human approval or waiver decision for an approval gate."""

    gate_type: str
    decision: str
    actor: str
    feedback: NotRequired[str | None]
    waivers: NotRequired[dict[str, Any] | None]
    timestamp: str


class ModernizationWorkflowState(TypedDict):
    """Authoritative, typed workflow state serialized into durable LangGraph checkpoints.

    CRITICAL ARCHITECTURAL RULE:
    Large binary files, inventories, or diffs must NEVER be embedded directly into this state.
    Only lightweight references (artifact_references) pointing to S3-compatible object storage
    and PostgreSQL metadata are stored here.
    """

    job_id: str
    tenant_id: str
    owner: str
    status: str
    current_step: str
    completed_steps: list[str]
    source_revision: str | None
    source_repo_url: str | None
    target_stack: dict[str, Any]
    budget: dict[str, Any]
    artifact_references: dict[str, dict[str, Any]]
    gate_approvals: dict[str, dict[str, Any]]
    needs_human: bool
    current_gate: str | None
    failure_reason: str | None
    failure_classification: str | None
    iteration_count: int
    metadata: dict[str, Any]
    idempotency_keys: list[str]
    rejection_history: list[dict[str, Any]]


@log_errors
def create_initial_workflow_state(
    *,
    job_id: uuid.UUID | str,
    tenant_id: uuid.UUID | str,
    owner: str,
    source_repo_url: str | None = None,
    source_revision: str | None = None,
    target_stack: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ModernizationWorkflowState:
    """Instantiate a validated, clean initial state for a modernization workflow."""
    try:
        return {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "owner": owner,
            "status": JobLifecycleState.QUEUED.value,
            "current_step": "initialized",
            "completed_steps": [],
            "source_revision": source_revision,
            "source_repo_url": source_repo_url,
            "target_stack": target_stack or {},
            "budget": budget or {},
            "artifact_references": {},
            "gate_approvals": {},
            "needs_human": False,
            "current_gate": None,
            "failure_reason": None,
            "failure_classification": None,
            "iteration_count": 0,
            "metadata": metadata or {},
            "idempotency_keys": [],
            "rejection_history": [],
        }
    except Exception as exc:
        logger.exception("create_initial_workflow_state failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def record_artifact_reference(
    state: ModernizationWorkflowState,
    *,
    artifact_type: str,
    artifact_id: uuid.UUID | str,
    storage_ref: str,
    content_hash: str,
    size_bytes: int | None = None,
    content_type: str | None = "application/json",
) -> dict[str, dict[str, Any]]:
    """Record an artifact pointer without loading or embedding its content into workflow state."""
    try:
        refs = dict(state.get("artifact_references", {}))
        refs[artifact_type] = {
            "artifact_id": str(artifact_id),
            "artifact_type": artifact_type,
            "storage_ref": storage_ref,
            "content_hash": content_hash,
            "size_bytes": size_bytes,
            "content_type": content_type,
        }
        return refs
    except Exception as exc:
        logger.exception("record_artifact_reference failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def is_step_completed(state: ModernizationWorkflowState, step_name: str) -> bool:
    """Check if a specific node or side-effect boundary has already succeeded."""
    try:
        completed = state.get("completed_steps", [])
        return step_name in completed
    except Exception as exc:
        logger.exception("is_step_completed failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def mark_step_completed(state: ModernizationWorkflowState, step_name: str) -> list[str]:
    """Append a step to the completed_steps array if not already recorded."""
    try:
        completed = list(state.get("completed_steps", []))
        if step_name not in completed:
            completed.append(step_name)
        return completed
    except Exception as exc:
        logger.exception("mark_step_completed failed | %s: %s", type(exc).__name__, exc)
        raise


__all__ = [
    "ArtifactReferenceDict",
    "GateDecisionRecord",
    "ModernizationWorkflowState",
    "create_initial_workflow_state",
    "is_step_completed",
    "mark_step_completed",
    "record_artifact_reference",
]
