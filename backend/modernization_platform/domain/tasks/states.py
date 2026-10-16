"""Task lifecycle states and failure classification enums."""

import logging
from enum import StrEnum

from modernization_platform.core.decorators import log_errors

logger = logging.getLogger(__name__)


class TaskLifecycleState(StrEnum):
    """Authoritative domain task lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskFailureClassification(StrEnum):
    """Classification of task failures determining retryability and recovery."""

    RETRYABLE_INFRASTRUCTURE_ERROR = "retryable_infrastructure_error"
    PERMANENT_FAILURE = "permanent_failure"
    CANCELLATION = "cancellation"
    TIMEOUT_EXPIRED = "timeout_expired"


TERMINAL_TASK_STATES: frozenset[TaskLifecycleState] = frozenset(
    {
        TaskLifecycleState.COMPLETED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.CANCELLED,
    }
)

ACTIVE_TASK_STATES: frozenset[TaskLifecycleState] = frozenset(
    {
        TaskLifecycleState.PENDING,
        TaskLifecycleState.RUNNING,
        TaskLifecycleState.RETRY_WAIT,
    }
)


@log_errors
def is_terminal_task_state(state: TaskLifecycleState | str) -> bool:
    """Check if a task state represents a terminal lifecycle state."""
    try:
        val = TaskLifecycleState(state) if isinstance(state, str) else state
        return val in TERMINAL_TASK_STATES
    except ValueError:
        return False
    except Exception as exc:
        logger.exception("is_terminal_task_state check failed | %s: %s", type(exc).__name__, exc)
        raise


__all__ = [
    "ACTIVE_TASK_STATES",
    "TERMINAL_TASK_STATES",
    "TaskFailureClassification",
    "TaskLifecycleState",
    "is_terminal_task_state",
]
