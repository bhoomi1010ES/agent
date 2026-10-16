"""Job domain models, lifecycle state machine, transitions, and errors."""

from modernization_platform.domain.jobs.errors import (
    IdempotencyConflictError,
    InvalidJobConfigurationError,
    InvalidStateTransitionError,
    JobCompletionBlockedError,
    JobConcurrencyConflictError,
    JobDomainError,
    JobNotFoundError,
    TerminalJobMutationError,
    UnauthorizedJobActionError,
)
from modernization_platform.domain.jobs.states import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    FailureClassification,
    JobLifecycleState,
    is_terminal_state,
)
from modernization_platform.domain.jobs.transitions import (
    LEGAL_TRANSITIONS,
    CompletionCheckResult,
    CompletionGuard,
    normalize_state,
    validate_transition,
)

__all__ = [
    "ACTIVE_STATES",
    "LEGAL_TRANSITIONS",
    "TERMINAL_STATES",
    "CompletionCheckResult",
    "CompletionGuard",
    "FailureClassification",
    "IdempotencyConflictError",
    "InvalidJobConfigurationError",
    "InvalidStateTransitionError",
    "JobCompletionBlockedError",
    "JobConcurrencyConflictError",
    "JobDomainError",
    "JobLifecycleState",
    "JobNotFoundError",
    "TerminalJobMutationError",
    "UnauthorizedJobActionError",
    "is_terminal_state",
    "normalize_state",
    "validate_transition",
]
