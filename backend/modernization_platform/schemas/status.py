"""Finite lifecycle status values used by API transport contracts."""

from enum import StrEnum


class JobStatus(StrEnum):
    """Persisted modernization job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class GateDecisionValue(StrEnum):
    """Human decision values accepted by a gate decision request."""

    APPROVED = "approved"
    REJECTED = "rejected"
