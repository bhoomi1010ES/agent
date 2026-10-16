"""Unit tests for Human Approval Gate state machine and transition rules."""

import pytest

from modernization_platform.domain.gates.errors import (
    InvalidGateStateTransitionError,
)
from modernization_platform.domain.gates.notifications import (
    GateNotificationDispatcher,
    GateNotificationEvent,
    GateNotificationType,
)
from modernization_platform.domain.gates.rejection import (
    get_rejection_target_stage,
)
from modernization_platform.domain.gates.states import (
    GateState,
    GateType,
    is_terminal_gate_state,
)
from modernization_platform.domain.gates.transitions import (
    validate_gate_transition,
)


def test_gate_types_enumeration() -> None:
    """Verify all four canonical TDD gates and escalation are defined."""
    assert GateType.G1_FEASIBILITY.value == "G1_FEASIBILITY"
    assert GateType.G2_CHARACTERIZATION.value == "G2_CHARACTERIZATION"
    assert GateType.G3_BLUEPRINT_PLAN.value == "G3_BLUEPRINT_PLAN"
    assert GateType.G4_INTEGRATION_PR.value == "G4_INTEGRATION_PR"
    assert GateType.ESCALATION.value == "ESCALATION"


def test_gate_states_enumeration() -> None:
    """Verify required gate lifecycle states are defined."""
    assert GateState.PENDING.value == "pending"
    assert GateState.APPROVED.value == "approved"
    assert GateState.REJECTED.value == "rejected"
    assert GateState.PAUSED.value == "paused"
    assert GateState.TIMED_OUT.value == "timed_out"
    assert GateState.CANCELLED.value == "cancelled"


def test_terminal_gate_states() -> None:
    """Verify terminal state detection and immutability."""
    assert is_terminal_gate_state(GateState.APPROVED) is True
    assert is_terminal_gate_state(GateState.REJECTED) is True
    assert is_terminal_gate_state(GateState.CANCELLED) is True
    assert is_terminal_gate_state(GateState.PENDING) is False
    assert is_terminal_gate_state(GateState.PAUSED) is False
    assert is_terminal_gate_state(GateState.TIMED_OUT) is False
    assert is_terminal_gate_state("UNKNOWN_STATE") is False


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        (GateState.PENDING, GateState.APPROVED),
        (GateState.PENDING, GateState.REJECTED),
        (GateState.PENDING, GateState.PAUSED),
        (GateState.PENDING, GateState.TIMED_OUT),
        (GateState.PENDING, GateState.CANCELLED),
        (GateState.PAUSED, GateState.PENDING),
        (GateState.PAUSED, GateState.CANCELLED),
        (GateState.TIMED_OUT, GateState.PAUSED),
        (GateState.TIMED_OUT, GateState.PENDING),
    ],
)
def test_legal_gate_transitions(from_state: GateState, to_state: GateState) -> None:
    """Verify legal state transitions succeed without error."""
    validate_gate_transition(from_state, to_state)


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        (GateState.APPROVED, GateState.PENDING),
        (GateState.APPROVED, GateState.REJECTED),
        (GateState.APPROVED, GateState.PAUSED),
        (GateState.REJECTED, GateState.APPROVED),
        (GateState.REJECTED, GateState.PENDING),
        (GateState.CANCELLED, GateState.PENDING),
        (GateState.CANCELLED, GateState.APPROVED),
        (GateState.PAUSED, GateState.APPROVED),
        (GateState.PAUSED, GateState.REJECTED),
    ],
)
def test_illegal_gate_transitions_raise(from_state: GateState, to_state: GateState) -> None:
    """Verify illegal state transitions raise InvalidGateStateTransitionError."""
    with pytest.raises(InvalidGateStateTransitionError) as exc_info:
        validate_gate_transition(from_state, to_state)
    assert exc_info.value.code == "INVALID_GATE_STATE_TRANSITION"


def test_rejection_target_mapping() -> None:
    """Verify each gate maps to its exact predecessor stage upon rejection."""
    assert get_rejection_target_stage(GateType.G1_FEASIBILITY) == "intake"
    assert get_rejection_target_stage(GateType.G2_CHARACTERIZATION) == "analysis"
    assert get_rejection_target_stage(GateType.G3_BLUEPRINT_PLAN) == "architecture"
    assert get_rejection_target_stage(GateType.G4_INTEGRATION_PR) == "conversion"
    assert get_rejection_target_stage(GateType.ESCALATION) == "intake"
    # String fallback
    assert get_rejection_target_stage("g1_feasibility") == "intake"
    assert get_rejection_target_stage("unknown_gate") == "intake"


@pytest.mark.asyncio
async def test_notification_dispatcher_hooks() -> None:
    """Verify GateNotificationDispatcher registers and invokes hooks."""
    import uuid

    dispatcher = GateNotificationDispatcher()
    received_events: list[GateNotificationEvent] = []

    async def sample_hook(event: GateNotificationEvent) -> None:
        received_events.append(event)

    dispatcher.register_hook(sample_hook)

    event = GateNotificationEvent(
        event_type=GateNotificationType.GATE_CREATED,
        gate_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        gate_type="G1_FEASIBILITY",
        details={"test": True},
    )

    await dispatcher.dispatch(event)
    assert len(received_events) == 1
    assert received_events[0].event_type == GateNotificationType.GATE_CREATED
    assert received_events[0].gate_type == "G1_FEASIBILITY"
