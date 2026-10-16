"""Job lifecycle states and failure classification enums."""

import logging
from enum import StrEnum

from modernization_platform.core.decorators import log_errors

logger = logging.getLogger(__name__)


class JobLifecycleState(StrEnum):
    """Authoritative domain job lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class FailureClassification(StrEnum):
    """Classification of failure determining retryability."""

    TRANSIENT = "transient"
    TERMINAL = "terminal"


TERMINAL_STATES: frozenset[JobLifecycleState] = frozenset(
    {
        JobLifecycleState.COMPLETED,
        JobLifecycleState.CANCELLED,
    }
)

ACTIVE_STATES: frozenset[JobLifecycleState] = frozenset(
    {
        JobLifecycleState.QUEUED,
        JobLifecycleState.RUNNING,
        JobLifecycleState.AWAITING_APPROVAL,
        JobLifecycleState.PAUSED,
    }
)


@log_errors
def is_terminal_state(state: JobLifecycleState | str) -> bool:
    """Check if a state represents a terminal lifecycle state."""
    try:
        val = JobLifecycleState(state) if isinstance(state, str) else state
        return val in TERMINAL_STATES
    except ValueError:
        return False


__all__ = [
    "ACTIVE_STATES",
    "TERMINAL_STATES",
    "FailureClassification",
    "JobLifecycleState",
    "is_terminal_state",
]
