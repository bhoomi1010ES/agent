"""Domain error hierarchy for human approval gates and audit decisions."""

from typing import Any

from modernization_platform.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    ModernizerError,
    NotFoundException,
)


class GateDomainError(ModernizerError):
    """Base exception for all human approval gate domain errors."""

    def __init__(self, message: str = "A gate domain error occurred.") -> None:
        super().__init__(message)
        self.message = message


class GateNotFoundError(GateDomainError, NotFoundException):
    """Raised when a requested approval gate does not exist."""

    def __init__(self, gate_id: str, details: Any | None = None) -> None:
        msg = f"Gate '{gate_id}' was not found."
        NotFoundException.__init__(
            self,
            message=msg,
            code="GATE_NOT_FOUND",
            details=details or {"gate_id": gate_id},
        )
        self.message = msg


class InvalidGateStateTransitionError(GateDomainError, ConflictException):
    """Raised when an illegal gate lifecycle transition is attempted."""

    def __init__(
        self,
        from_state: str,
        to_state: str,
        reason: str | None = None,
        details: Any | None = None,
    ) -> None:
        msg = f"Invalid gate state transition from '{from_state}' to '{to_state}'."
        if reason:
            msg += f" Reason: {reason}"
        ConflictException.__init__(
            self,
            message=msg,
            code="INVALID_GATE_STATE_TRANSITION",
            details=details or {"from_state": from_state, "to_state": to_state, "reason": reason},
        )
        self.message = msg


class GateClosedError(GateDomainError, ConflictException):
    """Raised when attempting to decide or mutate an already resolved/closed gate."""

    def __init__(self, gate_id: str, current_state: str, details: Any | None = None) -> None:
        msg = (
            f"Gate '{gate_id}' is closed with state '{current_state}' and cannot accept decisions."
        )
        ConflictException.__init__(
            self,
            message=msg,
            code="GATE_ALREADY_CLOSED",
            details=details or {"gate_id": gate_id, "state": current_state},
        )
        self.message = msg


class DuplicateDecisionError(GateDomainError, ConflictException):
    """Raised when a decision has already been recorded or duplicate decision is attempted."""

    def __init__(self, gate_id: str, details: Any | None = None) -> None:
        msg = f"A decision has already been recorded for gate '{gate_id}'."
        ConflictException.__init__(
            self,
            message=msg,
            code="DUPLICATE_GATE_DECISION",
            details=details or {"gate_id": gate_id},
        )
        self.message = msg


class StaleArtifactVersionError(GateDomainError, ConflictException):
    """Raised when the artifact version presented at decision time differs from gate creation."""

    def __init__(
        self,
        artifact_id: str,
        expected_version: int,
        actual_version: int,
        details: Any | None = None,
    ) -> None:
        msg = (
            f"Stale artifact version for '{artifact_id}': gate reviewed version {expected_version}, "
            f"but current authoritative version is {actual_version}."
        )
        ConflictException.__init__(
            self,
            message=msg,
            code="STALE_ARTIFACT_VERSION",
            details=details
            or {
                "artifact_id": artifact_id,
                "expected_version": expected_version,
                "actual_version": actual_version,
            },
        )
        self.message = msg


class UnauthorizedReviewerError(GateDomainError, ForbiddenException):
    """Raised when the authenticated principal is not authorized to decide this gate."""

    def __init__(self, user_id: str, gate_type: str, details: Any | None = None) -> None:
        msg = f"User '{user_id}' is not authorized to decide gate of type '{gate_type}'."
        ForbiddenException.__init__(
            self,
            message=msg,
            code="UNAUTHORIZED_REVIEWER",
            details=details or {"user_id": user_id, "gate_type": gate_type},
        )
        self.message = msg


class MissingRejectionRationaleError(GateDomainError, BadRequestException):
    """Raised when a gate rejection is submitted without mandatory non-whitespace rationale."""

    def __init__(self, gate_id: str, details: Any | None = None) -> None:
        msg = f"Rejection of gate '{gate_id}' requires a non-empty, non-whitespace rationale."
        BadRequestException.__init__(
            self,
            message=msg,
            code="MISSING_REJECTION_RATIONALE",
            details=details or {"gate_id": gate_id},
        )
        self.message = msg


class InvalidWaiverError(GateDomainError, BadRequestException):
    """Raised when an intended-difference waiver is invalid or missing required fields."""

    def __init__(self, reason: str, details: Any | None = None) -> None:
        msg = f"Invalid waiver request: {reason}"
        BadRequestException.__init__(
            self,
            message=msg,
            code="INVALID_WAIVER",
            details=details or {"reason": reason},
        )
        self.message = msg


class GateTimeoutError(GateDomainError, ConflictException):
    """Raised when an operation cannot proceed because the gate has timed out."""

    def __init__(self, gate_id: str, details: Any | None = None) -> None:
        msg = f"Gate '{gate_id}' has timed out and is paused."
        ConflictException.__init__(
            self,
            message=msg,
            code="GATE_TIMED_OUT",
            details=details or {"gate_id": gate_id},
        )
        self.message = msg


__all__ = [
    "DuplicateDecisionError",
    "GateClosedError",
    "GateDomainError",
    "GateNotFoundError",
    "GateTimeoutError",
    "InvalidGateStateTransitionError",
    "InvalidWaiverError",
    "MissingRejectionRationaleError",
    "StaleArtifactVersionError",
    "UnauthorizedReviewerError",
]
