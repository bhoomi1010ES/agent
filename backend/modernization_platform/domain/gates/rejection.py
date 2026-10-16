"""Rejection routing policies and mapping for approval gates."""

import logging
from collections.abc import Mapping

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.gates.states import GateType

logger = logging.getLogger(__name__)

GATE_REJECTION_TARGETS: Mapping[GateType, str] = {
    GateType.G1_FEASIBILITY: "intake",
    GateType.G2_CHARACTERIZATION: "analysis",
    GateType.G3_BLUEPRINT_PLAN: "architecture",
    GateType.G4_INTEGRATION_PR: "conversion",
    GateType.ESCALATION: "intake",
}


@log_errors
def get_rejection_target_stage(gate_type: GateType | str) -> str:
    """Return the designated earlier workflow stage to return to upon gate rejection.

    Mapping:
        G1_FEASIBILITY      -> intake
        G2_CHARACTERIZATION -> analysis
        G3_BLUEPRINT_PLAN   -> architecture
        G4_INTEGRATION_PR   -> conversion
        ESCALATION          -> intake
    """
    try:
        gtype = gate_type if isinstance(gate_type, GateType) else GateType(str(gate_type).upper())
        target = GATE_REJECTION_TARGETS.get(gtype, "intake")
        logger.info("Determined rejection target stage for gate '%s' -> '%s'", gtype.value, target)
        return target
    except Exception as exc:
        logger.warning(
            "Failed resolving rejection target for gate_type '%s', falling back to 'intake': %s",
            gate_type,
            exc,
            exc_info=True,
        )
        return "intake"


__all__ = [
    "GATE_REJECTION_TARGETS",
    "get_rejection_target_stage",
]
