"""Finite lifecycle status values used by API transport contracts."""

from enum import StrEnum


class JobStatus(StrEnum):
    """Persisted modernization job lifecycle states."""

    QUEUED = "queued"
    PENDING = "pending"  # Legacy compatibility alias
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class GateDecisionValue(StrEnum):
    """Human decision values accepted by a gate decision request."""

    APPROVED = "approved"
    REJECTED = "rejected"
    WAIVED = "waived"


__all__ = ["GateDecisionValue", "JobStatus"]
