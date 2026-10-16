"""Gate decision transport contracts that keep actor identity server-assigned."""

import uuid
from typing import Any

from pydantic import AwareDatetime, Field, model_validator

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.base import LongText, TransportRequest, TransportResponse
from modernization_platform.schemas.status import GateDecisionValue


class WaiverRequest(TransportRequest):
    """A requested waiver whose reviewer identity is recorded by the gate service."""

    subject: str = Field(min_length=1, max_length=200)
    reason: LongText


class GateDecisionRequest(TransportRequest):
    """Human decision input; callers cannot assert actor identity or approval state."""

    decision: GateDecisionValue
    feedback: LongText | None = None
    waivers: list[WaiverRequest] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    @log_errors
    def validate_decision_details(self) -> "GateDecisionRequest":
        if self.decision is GateDecisionValue.REJECTED and self.feedback is None:
            raise ValueError("rejected decisions require written feedback")
        return self


class GateDecisionResponse(TransportResponse):
    """Confirmed append-only gate decision record."""

    gate_id: uuid.UUID
    decision_id: uuid.UUID
    decision: GateDecisionValue
    decided_at: AwareDatetime


class GateDetailResponse(TransportResponse):
    """Human approval gate status and presented review context."""

    gate_id: uuid.UUID
    job_id: uuid.UUID
    gate_type: str
    state: str
    requested_at: AwareDatetime
    artifact_versions_shown: dict[str, Any] = Field(default_factory=dict)
    needs_human_flags: list[dict[str, Any]] = Field(default_factory=list)
    budget_used_cents: float = 0.0
    resolved_at: AwareDatetime | None = None


class GateListResponse(TransportResponse):
    """List of gates associated with an authorized job."""

    items: list[GateDetailResponse]
    total: int
