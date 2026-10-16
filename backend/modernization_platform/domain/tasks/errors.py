"""Domain exceptions for task persistence, state transitions, and worker lease handling."""

from modernization_platform.core.exceptions import ModernizerError


class TaskError(ModernizerError):
    """Base exception for all task-related errors."""


class InvalidTaskStateTransitionError(TaskError):
    """Raised when an illegal transition is requested between task states."""


class TaskClaimError(TaskError):
    """Raised when claiming a task fails due to concurrency or lock conflict."""


class LeaseLostError(TaskError):
    """Raised when a worker attempts an operation on a task whose lease was lost, expired, or stolen."""


class TaskMaxAttemptsExceededError(TaskError):
    """Raised when a task exceeds its maximum allowed execution attempts."""


class DuplicateFinalizationError(TaskError):
    """Raised when a task has already been finalized and another worker attempts completion."""


__all__ = [
    "DuplicateFinalizationError",
    "InvalidTaskStateTransitionError",
    "LeaseLostError",
    "TaskClaimError",
    "TaskError",
    "TaskMaxAttemptsExceededError",
]
