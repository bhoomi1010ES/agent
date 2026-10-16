"""Domain models, state machine, and retry policies for durable tasks."""

from modernization_platform.domain.tasks.errors import (
    DuplicateFinalizationError,
    InvalidTaskStateTransitionError,
    LeaseLostError,
    TaskClaimError,
    TaskError,
    TaskMaxAttemptsExceededError,
)
from modernization_platform.domain.tasks.retry import (
    TaskRetryPolicy,
    calculate_backoff,
    classify_exception,
    should_retry,
)
from modernization_platform.domain.tasks.states import (
    ACTIVE_TASK_STATES,
    TERMINAL_TASK_STATES,
    TaskFailureClassification,
    TaskLifecycleState,
    is_terminal_task_state,
)
from modernization_platform.domain.tasks.transitions import (
    LEGAL_TASK_TRANSITIONS,
    validate_task_transition,
)

__all__ = [
    "ACTIVE_TASK_STATES",
    "LEGAL_TASK_TRANSITIONS",
    "TERMINAL_TASK_STATES",
    "DuplicateFinalizationError",
    "InvalidTaskStateTransitionError",
    "LeaseLostError",
    "TaskClaimError",
    "TaskError",
    "TaskFailureClassification",
    "TaskLifecycleState",
    "TaskMaxAttemptsExceededError",
    "TaskRetryPolicy",
    "calculate_backoff",
    "classify_exception",
    "is_terminal_task_state",
    "should_retry",
    "validate_task_transition",
]
