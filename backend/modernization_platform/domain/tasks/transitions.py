"""Authoritative state machine transition rules for durable tasks."""

import logging

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.tasks.errors import InvalidTaskStateTransitionError
from modernization_platform.domain.tasks.states import (
    TERMINAL_TASK_STATES,
    TaskLifecycleState,
)

logger = logging.getLogger(__name__)

# Single authoritative transition matrix for task lifecycle
LEGAL_TASK_TRANSITIONS: dict[TaskLifecycleState, frozenset[TaskLifecycleState]] = {
    TaskLifecycleState.PENDING: frozenset(
        {
            TaskLifecycleState.RUNNING,
            TaskLifecycleState.CANCELLED,
        }
    ),
    TaskLifecycleState.RUNNING: frozenset(
        {
            TaskLifecycleState.COMPLETED,
            TaskLifecycleState.FAILED,
            TaskLifecycleState.RETRY_WAIT,
            TaskLifecycleState.CANCELLED,
            TaskLifecycleState.PENDING,  # Graceful release / abandonment for re-claiming
        }
    ),
    TaskLifecycleState.RETRY_WAIT: frozenset(
        {
            TaskLifecycleState.PENDING,
            TaskLifecycleState.RUNNING,
            TaskLifecycleState.CANCELLED,
            TaskLifecycleState.FAILED,
        }
    ),
    TaskLifecycleState.COMPLETED: frozenset(),
    TaskLifecycleState.FAILED: frozenset(),
    TaskLifecycleState.CANCELLED: frozenset(),
}


@log_errors
def validate_task_transition(
    current_state: TaskLifecycleState | str,
    next_state: TaskLifecycleState | str,
) -> None:
    """Validate whether transitioning from current_state to next_state is legal.

    Raises:
        InvalidTaskStateTransitionError: If the transition is prohibited.
    """
    try:
        current = (
            TaskLifecycleState(current_state) if isinstance(current_state, str) else current_state
        )
        target = TaskLifecycleState(next_state) if isinstance(next_state, str) else next_state

        if current in TERMINAL_TASK_STATES:
            raise InvalidTaskStateTransitionError(
                f"Cannot mutate task in terminal state '{current}' to '{target}'"
            )

        allowed = LEGAL_TASK_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise InvalidTaskStateTransitionError(
                f"Illegal task transition from '{current}' to '{target}'. Permitted: {sorted(s.value for s in allowed)}"
            )
    except InvalidTaskStateTransitionError:
        raise
    except Exception as exc:
        logger.exception("validate_task_transition failed | %s: %s", type(exc).__name__, exc)
        raise


__all__ = [
    "LEGAL_TASK_TRANSITIONS",
    "validate_task_transition",
]
