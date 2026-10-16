"""Unit tests for workflow state, artifact reference boundaries, and idempotency tracking."""

import uuid

from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.workflows.state import (
    create_initial_workflow_state,
    is_step_completed,
    mark_step_completed,
    record_artifact_reference,
)


def test_initial_workflow_state_creation() -> None:
    """Initial workflow state captures stable identifiers and defaults to queued."""
    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    owner = "engineer@example.com"

    state = create_initial_workflow_state(
        job_id=job_id,
        tenant_id=tenant_id,
        owner=owner,
        source_repo_url="https://github.com/example/repo.git",
        source_revision="main",
        target_stack={"language": "python", "framework": "fastapi"},
        budget={"max_usd": 100.0},
    )

    assert state["job_id"] == str(job_id)
    assert state["tenant_id"] == str(tenant_id)
    assert state["owner"] == owner
    assert state["status"] == JobLifecycleState.QUEUED.value
    assert state["current_step"] == "initialized"
    assert state["completed_steps"] == []
    assert state["artifact_references"] == {}
    assert state["gate_approvals"] == {}
    assert state["needs_human"] is False
    assert state["iteration_count"] == 0


def test_artifact_references_never_embed_large_payloads() -> None:
    """Artifact references store pointers to object storage and hashes, never raw payload bytes."""
    state = create_initial_workflow_state(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        owner="test-owner",
    )
    art_id = uuid.uuid4()
    storage_ref = "s3://modernization-artifacts/inventory.json"
    content_hash = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"

    updated_refs = record_artifact_reference(
        state,
        artifact_type="RepoInventory",
        artifact_id=art_id,
        storage_ref=storage_ref,
        content_hash=content_hash,
        size_bytes=1024,
        content_type="application/json",
    )

    state["artifact_references"] = updated_refs
    ref = state["artifact_references"]["RepoInventory"]

    assert ref["artifact_id"] == str(art_id)
    assert ref["storage_ref"] == storage_ref
    assert ref["content_hash"] == content_hash
    assert ref["size_bytes"] == 1024
    assert ref["content_type"] == "application/json"
    # Ensure no large arbitrary content keys are embedded
    assert "content" not in ref
    assert "data" not in ref
    assert "payload" not in ref


def test_step_completion_tracking_and_idempotency_helpers() -> None:
    """Idempotency tracking records executed steps and prevents duplicate entries."""
    state = create_initial_workflow_state(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        owner="test-owner",
    )

    assert is_step_completed(state, "intake") is False

    state["completed_steps"] = mark_step_completed(state, "intake")
    assert is_step_completed(state, "intake") is True
    assert state["completed_steps"] == ["intake"]

    # Marking the same step completed again is idempotent
    state["completed_steps"] = mark_step_completed(state, "intake")
    assert state["completed_steps"] == ["intake"]

    # Marking a second step appends in order
    state["completed_steps"] = mark_step_completed(state, "analysis")
    assert state["completed_steps"] == ["intake", "analysis"]
    assert is_step_completed(state, "analysis") is True
    assert is_step_completed(state, "conversion") is False
