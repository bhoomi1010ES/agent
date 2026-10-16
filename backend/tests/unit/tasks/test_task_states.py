"""Unit tests validating task lifecycle states and state transitions."""

import pytest

from modernization_platform.domain.tasks.errors import InvalidTaskStateTransitionError
from modernization_platform.domain.tasks.states import (
    TaskLifecycleState,
    is_terminal_task_state,
)
from modernization_platform.domain.tasks.transitions import (
    LEGAL_TASK_TRANSITIONS,
    validate_task_transition,
)


def test_terminal_states() -> None:
    """Completed, failed, and cancelled are terminal states; others are not."""
    assert is_terminal_task_state(TaskLifecycleState.COMPLETED) is True
    assert is_terminal_task_state(TaskLifecycleState.FAILED) is True
    assert is_terminal_task_state(TaskLifecycleState.CANCELLED) is True
    assert is_terminal_task_state(TaskLifecycleState.PENDING) is False
    assert is_terminal_task_state(TaskLifecycleState.RUNNING) is False
    assert is_terminal_task_state(TaskLifecycleState.RETRY_WAIT) is False


def test_legal_transitions_validation() -> None:
    """All valid state transitions succeed without error."""
    # pending -> running, cancelled
    validate_task_transition(TaskLifecycleState.PENDING, TaskLifecycleState.RUNNING)
    validate_task_transition(TaskLifecycleState.PENDING, TaskLifecycleState.CANCELLED)

    # running -> completed, retry_wait, failed, cancelled, pending
    validate_task_transition(TaskLifecycleState.RUNNING, TaskLifecycleState.COMPLETED)
    validate_task_transition(TaskLifecycleState.RUNNING, TaskLifecycleState.RETRY_WAIT)
    validate_task_transition(TaskLifecycleState.RUNNING, TaskLifecycleState.FAILED)
    validate_task_transition(TaskLifecycleState.RUNNING, TaskLifecycleState.CANCELLED)
    validate_task_transition(TaskLifecycleState.RUNNING, TaskLifecycleState.PENDING)

    # retry_wait -> running, cancelled
    validate_task_transition(TaskLifecycleState.RETRY_WAIT, TaskLifecycleState.RUNNING)
    validate_task_transition(TaskLifecycleState.RETRY_WAIT, TaskLifecycleState.CANCELLED)


def test_illegal_transitions_raise_error() -> None:
    """Illegal state transitions raise InvalidTaskStateTransitionError."""
    # Terminal states cannot transition to anything
    with pytest.raises(InvalidTaskStateTransitionError) as exc_info:
        validate_task_transition(TaskLifecycleState.COMPLETED, TaskLifecycleState.RUNNING)
    assert "terminal state 'completed'" in str(exc_info.value)

    with pytest.raises(InvalidTaskStateTransitionError):
        validate_task_transition(TaskLifecycleState.FAILED, TaskLifecycleState.PENDING)

    with pytest.raises(InvalidTaskStateTransitionError):
        validate_task_transition(TaskLifecycleState.CANCELLED, TaskLifecycleState.RUNNING)

    # Pending cannot jump directly to completed
    with pytest.raises(InvalidTaskStateTransitionError) as exc_non_terminal:
        validate_task_transition(TaskLifecycleState.PENDING, TaskLifecycleState.COMPLETED)
    assert "Illegal task transition from 'pending' to 'completed'" in str(exc_non_terminal.value)

    # Pending cannot jump directly to retry_wait
    with pytest.raises(InvalidTaskStateTransitionError):
        validate_task_transition(TaskLifecycleState.PENDING, TaskLifecycleState.RETRY_WAIT)


def test_legal_transitions_dictionary_integrity() -> None:
    """Verify that every lifecycle state is present in the transition map."""
    for state in TaskLifecycleState:
        assert state in LEGAL_TASK_TRANSITIONS
        allowed = LEGAL_TASK_TRANSITIONS[state]
        assert isinstance(allowed, frozenset)
