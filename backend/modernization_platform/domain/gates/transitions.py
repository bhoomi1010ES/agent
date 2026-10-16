"""State transition validation and rules for approval gates."""

import logging
from collections.abc import Mapping

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.gates.errors import InvalidGateStateTransitionError
from modernization_platform.domain.gates.states import GateState

logger = logging.getLogger(__name__)

LEGAL_GATE_TRANSITIONS: Mapping[GateState, frozenset[GateState]] = {
    GateState.PENDING: frozenset(
        {
            GateState.APPROVED,
            GateState.REJECTED,
            GateState.PAUSED,
            GateState.TIMED_OUT,
            GateState.CANCELLED,
        }
    ),
    GateState.PAUSED: frozenset(
        {
            GateState.PENDING,
            GateState.CANCELLED,
        }
    ),
    GateState.TIMED_OUT: frozenset(
        {
            GateState.PAUSED,
            GateState.PENDING,
            GateState.CANCELLED,
        }
    ),
    GateState.APPROVED: frozenset(),
    GateState.REJECTED: frozenset(),
    GateState.CANCELLED: frozenset(),
}


@log_errors
def validate_gate_transition(from_state: GateState | str, to_state: GateState | str) -> None:
    """Validate that transitioning from `from_state` to `to_state` is legal.

    Raises:
        InvalidGateStateTransitionError: If the transition is prohibited.
    """
    try:
        source = (
            from_state if isinstance(from_state, GateState) else GateState(str(from_state).lower())
        )
        target = to_state if isinstance(to_state, GateState) else GateState(str(to_state).lower())
    except ValueError as exc:
        logger.warning(
            "Invalid gate state value during transition check: %s -> %s",
            from_state,
            to_state,
            exc_info=True,
        )
        raise InvalidGateStateTransitionError(
            from_state=str(from_state),
            to_state=str(to_state),
            reason=f"Unrecognized gate state: {exc}",
        ) from exc

    allowed = LEGAL_GATE_TRANSITIONS.get(source, frozenset())
    if target not in allowed:
        logger.warning(
            "Forbidden gate transition attempted from '%s' to '%s'. Allowed: %s",
            source.value,
            target.value,
            [s.value for s in allowed],
        )
        raise InvalidGateStateTransitionError(
            from_state=source.value,
            to_state=target.value,
            reason=f"Transition from '{source.value}' to '{target.value}' is prohibited.",
        )


__all__ = [
    "LEGAL_GATE_TRANSITIONS",
    "validate_gate_transition",
]
