"""Gate decision transport contracts that keep actor identity server-assigned."""

import uuid
from typing import Any

from pydantic import AwareDatetime, Field, field_validator, model_validator

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.base import LongText, TransportRequest, TransportResponse
from modernization_platform.schemas.status import GateDecisionValue


class WaiverRequest(TransportRequest):
    """A requested waiver whose reviewer identity is recorded by the gate service."""

    subject: str = Field(min_length=1, max_length=200)
    reason: LongText


class GateApproveRequest(TransportRequest):
    """Approval payload with optional rationale and exact artifact version references."""

    reason: str | None = Field(default=None, max_length=5000)
    artifact_versions: dict[str, Any] | None = None
    artifact_diff_ref: str | None = Field(default=None, max_length=512)


class GateRejectRequest(TransportRequest):
    """Rejection payload requiring mandatory written rationale and optional routing controls."""

    reason: str = Field(min_length=1, max_length=5000)
    artifact_versions: dict[str, Any] | None = None
    artifact_diff_ref: str | None = Field(default=None, max_length=512)
    return_to_stage: bool = True
    rejection_target: str | None = None

    @field_validator("reason")
    @classmethod
    @log_errors
    def validate_non_whitespace_reason(cls, value: str) -> str:
        try:
            if not value or not value.strip():
                raise ValueError("Rejection reason must not be blank or whitespace-only.")
            return value.strip()
        except Exception:
            raise


class GateDecisionRequest(TransportRequest):
    """Human decision input; callers cannot assert actor identity or approval state."""

    decision: GateDecisionValue
    feedback: LongText | None = None
    reason: LongText | None = None
    artifact_versions: dict[str, Any] | None = None
    artifact_diff_ref: str | None = Field(default=None, max_length=512)
    waivers: list[WaiverRequest] = Field(default_factory=list, max_length=100)
    return_to_stage: bool = True
    rejection_target: str | None = None

    @model_validator(mode="after")
    @log_errors
    def validate_decision_details(self) -> "GateDecisionRequest":
        effective_feedback = self.reason or self.feedback
        if self.decision is GateDecisionValue.REJECTED and (
            not effective_feedback or not str(effective_feedback).strip()
        ):
            raise ValueError("rejected decisions require written non-empty feedback/reason")
        return self


class GateResumeRequest(TransportRequest):
    """Request to resume a paused gate."""

    reason: str | None = Field(default=None, max_length=1000)


class GateCreateRequest(TransportRequest):
    """Manual or worker request to register an approval gate."""

    gate_type: str = Field(min_length=1, max_length=50)
    timeout_seconds: int | None = Field(default=None, ge=1, le=2592000)
    artifact_versions_shown: dict[str, Any] = Field(default_factory=dict)
    artifact_diff_ref: str | None = Field(default=None, max_length=512)
    needs_human_flags: list[dict[str, Any]] = Field(default_factory=list)
    budget_used_cents: float = 0.0
    workflow_thread_id: str | None = None


class GateDecisionDetailResponse(TransportResponse):
    """Immutable audit record of a gate decision."""

    id: uuid.UUID
    gate_id: uuid.UUID
    job_id: uuid.UUID | None = None
    gate_type: str | None = None
    actor: str
    actor_user_id: uuid.UUID | None = None
    approver_role: str | None = None
    decision: str
    feedback: str | None = None
    waivers: dict[str, Any] | None = None
    artifact_version_refs: dict[str, Any] | None = None
    artifact_diff_ref: str | None = None
    decided_at: AwareDatetime


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
    timeout_at: AwareDatetime | None = None
    workflow_thread_id: str | None = None
    artifact_versions_shown: dict[str, Any] = Field(default_factory=dict)
    artifact_diff_ref: str | None = None
    needs_human_flags: list[dict[str, Any]] = Field(default_factory=list)
    budget_used_cents: float = 0.0
    resolved_at: AwareDatetime | None = None
    resolved_by: str | None = None
    resolved_by_user_id: uuid.UUID | None = None
    updated_at: AwareDatetime | None = None
    decisions: list[GateDecisionDetailResponse] = Field(default_factory=list)


class GateListResponse(TransportResponse):
    """List of gates associated with an authorized job."""

    items: list[GateDetailResponse]
    total: int


__all__ = [
    "GateApproveRequest",
    "GateCreateRequest",
    "GateDecisionDetailResponse",
    "GateDecisionRequest",
    "GateDecisionResponse",
    "GateDetailResponse",
    "GateListResponse",
    "GateRejectRequest",
    "GateResumeRequest",
    "WaiverRequest",
]
