"""Unit tests for JobStateMachine legal/illegal transitions, terminal protection, and CompletionGuard."""

from types import SimpleNamespace

import pytest

from modernization_platform.domain.jobs.errors import (
    InvalidStateTransitionError,
    JobCompletionBlockedError,
    TerminalJobMutationError,
)
from modernization_platform.domain.jobs.states import (
    FailureClassification,
    JobLifecycleState,
)
from modernization_platform.domain.jobs.transitions import (
    CompletionCheckResult,
    CompletionGuard,
    validate_transition,
)


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (JobLifecycleState.QUEUED, JobLifecycleState.RUNNING),
        (JobLifecycleState.QUEUED, JobLifecycleState.CANCELLED),
        (JobLifecycleState.RUNNING, JobLifecycleState.AWAITING_APPROVAL),
        (JobLifecycleState.RUNNING, JobLifecycleState.PAUSED),
        (JobLifecycleState.RUNNING, JobLifecycleState.FAILED),
        (JobLifecycleState.RUNNING, JobLifecycleState.CANCELLED),
        (JobLifecycleState.PAUSED, JobLifecycleState.RUNNING),
        (JobLifecycleState.PAUSED, JobLifecycleState.CANCELLED),
        (JobLifecycleState.AWAITING_APPROVAL, JobLifecycleState.RUNNING),
        (JobLifecycleState.AWAITING_APPROVAL, JobLifecycleState.CANCELLED),
        (JobLifecycleState.AWAITING_APPROVAL, JobLifecycleState.FAILED),
    ],
)
def test_legal_state_transitions(
    from_state: JobLifecycleState, to_state: JobLifecycleState
) -> None:
    """Verify all standard legal transitions succeed."""
    curr, target = validate_transition(from_state, to_state)
    assert curr == from_state
    assert target == to_state


def test_failed_to_running_with_transient_failure_allowed() -> None:
    """Verify failed job with transient failure can transition back to running."""
    curr, target = validate_transition(
        JobLifecycleState.FAILED,
        JobLifecycleState.RUNNING,
        failure_classification=FailureClassification.TRANSIENT,
    )
    assert curr == JobLifecycleState.FAILED
    assert target == JobLifecycleState.RUNNING


def test_failed_to_running_with_explicit_retry_allowed() -> None:
    """Verify failed job with terminal failure can transition back to running when explicit retry is set."""
    curr, target = validate_transition(
        JobLifecycleState.FAILED,
        JobLifecycleState.RUNNING,
        failure_classification=FailureClassification.TERMINAL,
        is_retry=True,
    )
    assert curr == JobLifecycleState.FAILED
    assert target == JobLifecycleState.RUNNING


def test_failed_to_running_blocked_for_terminal_failure_without_retry() -> None:
    """Verify failed job with terminal failure cannot automatically resume without explicit retry."""
    with pytest.raises(
        InvalidStateTransitionError, match="cannot be resumed without explicit retry"
    ):
        validate_transition(
            JobLifecycleState.FAILED,
            JobLifecycleState.RUNNING,
            failure_classification=FailureClassification.TERMINAL,
            is_retry=False,
        )


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (JobLifecycleState.QUEUED, JobLifecycleState.PAUSED),
        (JobLifecycleState.QUEUED, JobLifecycleState.COMPLETED),
        (JobLifecycleState.QUEUED, JobLifecycleState.FAILED),
        (JobLifecycleState.PAUSED, JobLifecycleState.COMPLETED),
        (JobLifecycleState.PAUSED, JobLifecycleState.FAILED),
        (JobLifecycleState.PAUSED, JobLifecycleState.AWAITING_APPROVAL),
        (JobLifecycleState.AWAITING_APPROVAL, JobLifecycleState.PAUSED),
        (JobLifecycleState.AWAITING_APPROVAL, JobLifecycleState.COMPLETED),
        (JobLifecycleState.FAILED, JobLifecycleState.PAUSED),
        (JobLifecycleState.FAILED, JobLifecycleState.COMPLETED),
    ],
)
def test_illegal_state_transitions_raise_error(
    from_state: JobLifecycleState, to_state: JobLifecycleState
) -> None:
    """Verify illegal transitions raise typed InvalidStateTransitionError."""
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(from_state, to_state)


@pytest.mark.parametrize("target_state", list(JobLifecycleState))
def test_completed_job_is_terminal_and_immutable(target_state: JobLifecycleState) -> None:
    """Verify completed job cannot transition to any other state."""
    with pytest.raises(
        TerminalJobMutationError, match="Cannot mutate job in terminal state 'completed'"
    ):
        validate_transition(JobLifecycleState.COMPLETED, target_state)


@pytest.mark.parametrize("target_state", list(JobLifecycleState))
def test_cancelled_job_is_terminal_and_immutable(target_state: JobLifecycleState) -> None:
    """Verify cancelled job cannot transition to any other state."""
    with pytest.raises(
        TerminalJobMutationError, match="Cannot mutate job in terminal state 'cancelled'"
    ):
        validate_transition(JobLifecycleState.CANCELLED, target_state)


def test_running_to_completed_allowed_when_guard_approves() -> None:
    """Verify RUNNING to COMPLETED succeeds when completion guard approves."""
    guard = CompletionCheckResult(allowed=True)
    curr, target = validate_transition(
        JobLifecycleState.RUNNING,
        JobLifecycleState.COMPLETED,
        guard_result=guard,
    )
    assert curr == JobLifecycleState.RUNNING
    assert target == JobLifecycleState.COMPLETED


def test_running_to_completed_rejected_when_guard_blocks() -> None:
    """Verify RUNNING to COMPLETED raises JobCompletionBlockedError when guard blocks."""
    guard = CompletionCheckResult(allowed=False, reason="Missing verification stage output")
    with pytest.raises(JobCompletionBlockedError, match="Missing verification stage output"):
        validate_transition(
            JobLifecycleState.RUNNING,
            JobLifecycleState.COMPLETED,
            guard_result=guard,
        )


def test_completion_guard_blocks_when_pending_gates_exist() -> None:
    """Verify CompletionGuard rejects completion when gates remain pending."""
    job = SimpleNamespace(status="running", current_stage="verification")
    result = CompletionGuard.can_complete(job, has_pending_gates=True)
    assert result.allowed is False
    assert "gates remain pending" in (result.reason or "")


def test_completion_guard_blocks_when_stages_incomplete() -> None:
    """Verify CompletionGuard rejects completion when prerequisite stages are missing."""
    job = SimpleNamespace(status="running", current_stage="conversion")
    result = CompletionGuard.can_complete(
        job,
        completed_stages=["intake", "analysis"],
        required_stages=["intake", "analysis", "architecture", "conversion", "verification"],
    )
    assert result.allowed is False
    assert "Required stages remain incomplete" in (result.reason or "")


def test_completion_guard_blocks_when_not_in_running_state() -> None:
    """Verify CompletionGuard blocks completion if job is queued or paused."""
    queued_job = SimpleNamespace(status="queued")
    res_queued = CompletionGuard.can_complete(queued_job)
    assert res_queued.allowed is False
    assert "must be in 'running' state" in (res_queued.reason or "")

    paused_job = SimpleNamespace(status="paused")
    res_paused = CompletionGuard.can_complete(paused_job)
    assert res_paused.allowed is False
    assert "must be in 'running' state" in (res_paused.reason or "")


def test_completion_guard_blocks_terminal_jobs() -> None:
    """Verify CompletionGuard blocks jobs that are already completed or cancelled."""
    comp_job = SimpleNamespace(status="completed")
    res_comp = CompletionGuard.can_complete(comp_job)
    assert res_comp.allowed is False
    assert "already in terminal state" in (res_comp.reason or "")

    canc_job = SimpleNamespace(status="cancelled")
    res_canc = CompletionGuard.can_complete(canc_job)
    assert res_canc.allowed is False
    assert "already in terminal state" in (res_canc.reason or "")


def test_completion_guard_allows_when_all_prerequisites_met() -> None:
    """Verify CompletionGuard approves completion when all stages are complete and no gates pending."""
    job = SimpleNamespace(status="running", current_stage="verification")
    stages = ["intake", "analysis", "architecture", "conversion", "verification"]
    result = CompletionGuard.can_complete(
        job,
        completed_stages=stages,
        required_stages=stages,
        has_pending_gates=False,
    )
    assert result.allowed is True
    assert result.reason is None
