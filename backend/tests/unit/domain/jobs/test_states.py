"""Unit tests for JobLifecycleState, FailureClassification, and state utilities."""

import pytest

from modernization_platform.domain.jobs.errors import InvalidStateTransitionError
from modernization_platform.domain.jobs.states import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    FailureClassification,
    JobLifecycleState,
    is_terminal_state,
)
from modernization_platform.domain.jobs.transitions import normalize_state


def test_job_lifecycle_states_exist() -> None:
    """Verify all 7 required lifecycle states are defined with exact string values."""
    assert JobLifecycleState.QUEUED.value == "queued"
    assert JobLifecycleState.RUNNING.value == "running"
    assert JobLifecycleState.AWAITING_APPROVAL.value == "awaiting_approval"
    assert JobLifecycleState.PAUSED.value == "paused"
    assert JobLifecycleState.FAILED.value == "failed"
    assert JobLifecycleState.CANCELLED.value == "cancelled"
    assert JobLifecycleState.COMPLETED.value == "completed"


def test_failure_classifications_exist() -> None:
    """Verify transient vs terminal failure classifications."""
    assert FailureClassification.TRANSIENT.value == "transient"
    assert FailureClassification.TERMINAL.value == "terminal"


def test_terminal_states_set() -> None:
    """Verify terminal states collection."""
    assert {
        JobLifecycleState.COMPLETED,
        JobLifecycleState.CANCELLED,
    } == TERMINAL_STATES
    assert is_terminal_state(JobLifecycleState.COMPLETED) is True
    assert is_terminal_state(JobLifecycleState.CANCELLED) is True
    assert is_terminal_state(JobLifecycleState.RUNNING) is False
    assert is_terminal_state(JobLifecycleState.QUEUED) is False
    assert is_terminal_state(JobLifecycleState.PAUSED) is False
    assert is_terminal_state(JobLifecycleState.FAILED) is False
    assert is_terminal_state(JobLifecycleState.AWAITING_APPROVAL) is False


def test_is_terminal_state_string_inputs() -> None:
    """Verify string inputs to is_terminal_state."""
    assert is_terminal_state("completed") is True
    assert is_terminal_state("cancelled") is True
    assert is_terminal_state("running") is False
    assert is_terminal_state("invalid_state") is False


def test_active_states_set() -> None:
    """Verify active states collection."""
    assert JobLifecycleState.QUEUED in ACTIVE_STATES
    assert JobLifecycleState.RUNNING in ACTIVE_STATES
    assert JobLifecycleState.AWAITING_APPROVAL in ACTIVE_STATES
    assert JobLifecycleState.PAUSED in ACTIVE_STATES
    assert JobLifecycleState.COMPLETED not in ACTIVE_STATES
    assert JobLifecycleState.CANCELLED not in ACTIVE_STATES


def test_normalize_state_maps_pending_to_queued() -> None:
    """Verify legacy 'pending' status is normalized to QUEUED."""
    assert normalize_state("pending") == JobLifecycleState.QUEUED
    assert normalize_state(JobLifecycleState.QUEUED) == JobLifecycleState.QUEUED
    assert normalize_state("running") == JobLifecycleState.RUNNING


def test_normalize_state_rejects_unknown_value() -> None:
    """Verify unknown string raises InvalidStateTransitionError."""
    with pytest.raises(InvalidStateTransitionError):
        normalize_state("unrecognized_xyz")
