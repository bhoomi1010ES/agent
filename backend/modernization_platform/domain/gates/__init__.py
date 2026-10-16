"""Human-in-the-Loop Approval Gates domain package."""

from modernization_platform.domain.gates.errors import (
    DuplicateDecisionError,
    GateClosedError,
    GateDomainError,
    GateNotFoundError,
    GateTimeoutError,
    InvalidGateStateTransitionError,
    InvalidWaiverError,
    MissingRejectionRationaleError,
    StaleArtifactVersionError,
    UnauthorizedReviewerError,
)
from modernization_platform.domain.gates.notifications import (
    GateNotificationDispatcher,
    GateNotificationEvent,
    GateNotificationHook,
    GateNotificationType,
    default_gate_dispatcher,
)
from modernization_platform.domain.gates.rejection import (
    GATE_REJECTION_TARGETS,
    get_rejection_target_stage,
)
from modernization_platform.domain.gates.states import (
    TERMINAL_GATE_STATES,
    GateDecisionType,
    GateState,
    GateType,
    is_terminal_gate_state,
)
from modernization_platform.domain.gates.transitions import (
    LEGAL_GATE_TRANSITIONS,
    validate_gate_transition,
)

__all__ = [
    "GATE_REJECTION_TARGETS",
    "LEGAL_GATE_TRANSITIONS",
    "TERMINAL_GATE_STATES",
    "DuplicateDecisionError",
    "GateClosedError",
    "GateDecisionType",
    "GateDomainError",
    "GateNotFoundError",
    "GateNotificationDispatcher",
    "GateNotificationEvent",
    "GateNotificationHook",
    "GateNotificationType",
    "GateState",
    "GateTimeoutError",
    "GateType",
    "InvalidGateStateTransitionError",
    "InvalidWaiverError",
    "MissingRejectionRationaleError",
    "StaleArtifactVersionError",
    "UnauthorizedReviewerError",
    "default_gate_dispatcher",
    "get_rejection_target_stage",
    "is_terminal_gate_state",
    "validate_gate_transition",
]
