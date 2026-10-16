"""Unit tests for GateService domain logic, authorization, stale artifacts, and timeouts."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from modernization_platform.core.exceptions import ForbiddenException
from modernization_platform.db.models.gate import Gate
from modernization_platform.domain.gates.errors import (
    DuplicateDecisionError,
    GateTimeoutError,
    InvalidWaiverError,
    MissingRejectionRationaleError,
    StaleArtifactVersionError,
)
from modernization_platform.domain.gates.states import GateState
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.gates import GateService


def _principal(role: Role = Role.APPROVER) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="test-approver",
        issuer="https://auth.modernization.internal",
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


@pytest.mark.asyncio
async def test_gate_decide_forbidden_for_unauthorized_role() -> None:
    """Non-approver role (e.g. REVIEWER without GATE_DECIDE) is rejected with ForbiddenException."""
    principal = _principal(Role.REVIEWER)
    session = AsyncMock()
    service = GateService(session)

    with pytest.raises(ForbiddenException):
        await service.decide_gate(
            principal=principal,
            gate_id=uuid.uuid4(),
            decision="approved",
        )


@pytest.mark.asyncio
async def test_gate_decide_rejects_missing_rejection_rationale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rejection requires non-empty, non-whitespace rationale."""
    principal = _principal(Role.APPROVER)
    session = AsyncMock()
    service = GateService(session)

    gate = Gate(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        gate_type="G1_FEASIBILITY",
        state=GateState.PENDING.value,
        artifact_versions_shown={},
    )
    monkeypatch.setattr(service._gates, "get_by_id_scoped", AsyncMock(return_value=gate))

    with pytest.raises(MissingRejectionRationaleError):
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            decision="rejected",
            reason="   ",  # whitespace only
        )


@pytest.mark.asyncio
async def test_gate_decide_rejects_stale_client_artifact_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approval attempt with an artifact version mismatch from gate creation is rejected."""
    principal = _principal(Role.APPROVER)
    session = AsyncMock()
    service = GateService(session)

    gate = Gate(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        gate_type="G1_FEASIBILITY",
        state=GateState.PENDING.value,
        artifact_versions_shown={"spec": 5},
    )
    monkeypatch.setattr(service._gates, "get_by_id_scoped", AsyncMock(return_value=gate))

    with pytest.raises(StaleArtifactVersionError) as exc_info:
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            decision="approved",
            artifact_versions={"spec": 6},  # Gate reviewed v5, but client approves v6
        )

    assert exc_info.value.code == "STALE_ARTIFACT_VERSION"
    assert "version 5" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gate_decide_rejects_when_database_artifact_version_increased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approval attempt is rejected if an artifact has advanced in the DB since gate was opened."""
    principal = _principal(Role.APPROVER)
    session = AsyncMock()
    service = GateService(session)

    art_id = uuid.uuid4()
    gate = Gate(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        gate_type="G2_CHARACTERIZATION",
        state=GateState.PENDING.value,
        artifact_versions_shown={str(art_id): 2},
    )
    monkeypatch.setattr(service._gates, "get_by_id_scoped", AsyncMock(return_value=gate))

    # In database, artifact is now at version 3
    db_artifact = MagicMock(id=art_id, version=3)
    monkeypatch.setattr(
        service._artifacts, "_get_by_id_unscoped", AsyncMock(return_value=db_artifact)
    )

    with pytest.raises(StaleArtifactVersionError) as exc_info:
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            decision="approved",
        )

    assert exc_info.value.code == "STALE_ARTIFACT_VERSION"


@pytest.mark.asyncio
async def test_gate_decide_expired_gate_transitions_to_paused_never_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When now >= gate.timeout_at, gate transitions to paused; never becomes approved."""
    principal = _principal(Role.APPROVER)
    session = AsyncMock()
    service = GateService(session)

    past_timeout = datetime.now(UTC) - timedelta(minutes=10)
    gate = Gate(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        gate_type="G3_BLUEPRINT_PLAN",
        state=GateState.PENDING.value,
        timeout_at=past_timeout,
        artifact_versions_shown={},
    )
    mock_transition = AsyncMock()
    monkeypatch.setattr(service._gates, "get_by_id_scoped", AsyncMock(return_value=gate))
    monkeypatch.setattr(service._gates, "transition_gate_state", mock_transition)

    with pytest.raises(GateTimeoutError):
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            decision="approved",
        )

    # Verify transition to PAUSED occurred
    mock_transition.assert_called_once_with(gate, GateState.PAUSED)


@pytest.mark.asyncio
async def test_duplicate_decision_rejected_on_terminal_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deciding on an already approved or rejected gate raises DuplicateDecisionError."""
    principal = _principal(Role.APPROVER)
    session = AsyncMock()
    service = GateService(session)

    gate = Gate(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        gate_type="G4_INTEGRATION_PR",
        state=GateState.APPROVED.value,
        artifact_versions_shown={},
    )
    monkeypatch.setattr(service._gates, "get_by_id_scoped", AsyncMock(return_value=gate))

    with pytest.raises(DuplicateDecisionError):
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            decision="approved",
        )


@pytest.mark.asyncio
async def test_waiver_requires_written_justification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Waiver decision requires explicit non-empty justification."""
    principal = _principal(Role.APPROVER)
    session = AsyncMock()
    service = GateService(session)

    gate = Gate(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        gate_type="G4_INTEGRATION_PR",
        state=GateState.PENDING.value,
        artifact_versions_shown={},
    )
    monkeypatch.setattr(service._gates, "get_by_id_scoped", AsyncMock(return_value=gate))

    with pytest.raises(InvalidWaiverError):
        await service.decide_gate(
            principal=principal,
            gate_id=gate.id,
            decision="waived",
            reason=None,
        )


@pytest.mark.asyncio
async def test_resume_paused_gate_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resuming a paused gate returns it to pending state."""
    principal = _principal(Role.APPROVER)
    session = AsyncMock()
    service = GateService(session)

    gate = Gate(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        gate_type="G1_FEASIBILITY",
        state=GateState.PAUSED.value,
        artifact_versions_shown={},
    )
    mock_transition = AsyncMock(return_value=gate)
    monkeypatch.setattr(service._gates, "get_by_id_scoped", AsyncMock(return_value=gate))
    monkeypatch.setattr(service._gates, "transition_gate_state", mock_transition)

    resumed = await service.resume_gate(
        principal=principal,
        gate_id=gate.id,
        reason="Reviewer resumed after timeout discussion",
    )
    assert resumed is not None
    mock_transition.assert_called_once_with(gate, GateState.PENDING)
