"""Domain error hierarchy for modernization job lifecycle and state operations."""

import logging
from typing import Any

from modernization_platform.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    ModernizerError,
    NotFoundException,
)

logger = logging.getLogger(__name__)


class JobDomainError(ModernizerError):
    """Base exception for all job domain lifecycle and state errors."""

    def __init__(self, message: str = "A job domain error occurred.") -> None:
        ModernizerError.__init__(self, message)
        self.message = message


class InvalidStateTransitionError(JobDomainError, ConflictException):
    """Raised when an illegal lifecycle state transition is attempted."""

    def __init__(
        self,
        from_state: str,
        to_state: str,
        reason: str | None = None,
        details: Any | None = None,
    ) -> None:
        msg = f"Invalid state transition from '{from_state}' to '{to_state}'."
        if reason:
            msg += f" Reason: {reason}"
        ConflictException.__init__(
            self,
            message=msg,
            code="INVALID_STATE_TRANSITION",
            details=details or {"from_state": from_state, "to_state": to_state, "reason": reason},
        )
        self.message = msg


class TerminalJobMutationError(JobDomainError, ConflictException):
    """Raised when attempting to modify or resume a job in a terminal state."""

    def __init__(self, state: str, details: Any | None = None) -> None:
        msg = f"Cannot mutate job in terminal state '{state}'."
        ConflictException.__init__(
            self,
            message=msg,
            code="TERMINAL_JOB_MUTATION",
            details=details or {"state": state},
        )
        self.message = msg


class JobConcurrencyConflictError(JobDomainError, ConflictException):
    """Raised when an update encounters a stale expected version (optimistic concurrency)."""

    def __init__(
        self,
        expected_version: int,
        actual_version: int,
        details: Any | None = None,
    ) -> None:
        msg = f"Stale job version: expected {expected_version}, but actual version is {actual_version}."
        ConflictException.__init__(
            self,
            message=msg,
            code="CONCURRENCY_CONFLICT",
            details=details
            or {"expected_version": expected_version, "actual_version": actual_version},
        )
        self.message = msg


class IdempotencyConflictError(JobDomainError, ConflictException):
    """Raised when an idempotency key is reused with differing request parameters."""

    def __init__(
        self,
        key: str,
        details: Any | None = None,
    ) -> None:
        msg = f"Idempotency key '{key}' was already used with different request parameters."
        ConflictException.__init__(
            self,
            message=msg,
            code="IDEMPOTENCY_CONFLICT",
            details=details or {"key": key},
        )
        self.message = msg


class JobCompletionBlockedError(JobDomainError, ConflictException):
    """Raised when a job attempts completion while required stages remain incomplete."""

    def __init__(
        self,
        reason: str,
        details: Any | None = None,
    ) -> None:
        msg = f"Job completion blocked: {reason}"
        ConflictException.__init__(
            self,
            message=msg,
            code="JOB_COMPLETION_BLOCKED",
            details=details or {"reason": reason},
        )
        self.message = msg


class JobNotFoundError(JobDomainError, NotFoundException):
    """Raised when a requested job does not exist or is inaccessible."""

    def __init__(self, job_id: str, details: Any | None = None) -> None:
        msg = f"Job '{job_id}' not found."
        NotFoundException.__init__(
            self,
            message=msg,
            code="JOB_NOT_FOUND",
            details=details or {"job_id": job_id},
        )
        self.message = msg


class UnauthorizedJobActionError(JobDomainError, ForbiddenException):
    """Raised when a principal is not authorized to perform an action on a job."""

    def __init__(self, action: str, job_id: str, details: Any | None = None) -> None:
        msg = f"Unauthorized to perform action '{action}' on job '{job_id}'."
        ForbiddenException.__init__(
            self,
            message=msg,
            code="FORBIDDEN",
            details=details or {"action": action, "job_id": job_id},
        )
        self.message = msg


class InvalidJobConfigurationError(JobDomainError, BadRequestException):
    """Raised when job input or parameters fail domain-level configuration validation."""

    def __init__(self, message: str, details: Any | None = None) -> None:
        BadRequestException.__init__(
            self,
            message=message,
            code="INVALID_JOB_CONFIGURATION",
            details=details,
        )
        self.message = message


__all__ = [
    "IdempotencyConflictError",
    "InvalidJobConfigurationError",
    "InvalidStateTransitionError",
    "JobCompletionBlockedError",
    "JobConcurrencyConflictError",
    "JobDomainError",
    "JobNotFoundError",
    "TerminalJobMutationError",
    "UnauthorizedJobActionError",
]
