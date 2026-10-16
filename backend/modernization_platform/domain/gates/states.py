"""Domain state and type definitions for Human-in-the-Loop Approval Gates."""

from enum import StrEnum

from modernization_platform.core.decorators import log_errors


class GateType(StrEnum):
    """Canonical TDD approval gate identifiers."""

    G1_FEASIBILITY = "G1_FEASIBILITY"
    G2_CHARACTERIZATION = "G2_CHARACTERIZATION"
    G3_BLUEPRINT_PLAN = "G3_BLUEPRINT_PLAN"
    G4_INTEGRATION_PR = "G4_INTEGRATION_PR"
    ESCALATION = "ESCALATION"


class GateState(StrEnum):
    """Lifecycle states for human approval gates."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAUSED = "paused"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class GateDecisionType(StrEnum):
    """Explicit human decision outcomes."""

    APPROVED = "approved"
    REJECTED = "rejected"
    WAIVED = "waived"


TERMINAL_GATE_STATES: frozenset[GateState] = frozenset(
    {
        GateState.APPROVED,
        GateState.REJECTED,
        GateState.CANCELLED,
    }
)


@log_errors
def is_terminal_gate_state(state: GateState | str) -> bool:
    """Return True if the gate state cannot be further transitioned."""
    try:
        val = state if isinstance(state, GateState) else GateState(str(state).lower())
        return val in TERMINAL_GATE_STATES
    except Exception:
        return False


__all__ = [
    "TERMINAL_GATE_STATES",
    "GateDecisionType",
    "GateState",
    "GateType",
    "is_terminal_gate_state",
]
