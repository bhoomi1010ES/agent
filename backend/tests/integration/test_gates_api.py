"""Integration tests for Gate decision contract verification and concurrency (Workstream D)."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.db.session import get_db_session
from modernization_platform.security.dependencies import get_current_principal
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal


def _principal(
    role: Role = Role.APPROVER,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="test-approver",
        issuer="https://auth.modernization.internal",
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


@pytest.fixture
def mock_db_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_decide_gate_authorized_approval(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """Authorized approver can approve a pending gate; commits atomically."""
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()
    gate = Gate(
        id=gate_id,
        job_id=job_id,
        gate_type="G1_FEASIBILITY",
        state="pending",
        artifact_versions_shown={},
        needs_human_flags=[],
        budget_used_cents=150.0,
    )

    decision_id = uuid.uuid4()
    gate_decision = GateDecision(
        id=decision_id,
        gate_id=gate_id,
        actor=str(principal.user_id),
        actor_user_id=principal.user_id,
        decision="approved",
        feedback="Looks solid.",
        decided_at=datetime.now(UTC),
    )

    with (
        patch(
            "modernization_platform.repositories.gates.GateRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=gate,
        ) as mock_get_gate,
        patch(
            "modernization_platform.repositories.gates.GateRepository.record_authorized_decision",
            new_callable=AsyncMock,
            return_value=gate_decision,
        ),
        patch(
            "modernization_platform.repositories.audit_events.AuditEventRepository.append_event",
            new_callable=AsyncMock,
        ),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    f"/api/v1/jobs/{job_id}/gates/{gate_id}/decisions",
                    json={"decision": "approved", "feedback": "Looks solid."},
                )

            assert response.status_code == 200
            data = response.json()
            assert data["gate_id"] == str(gate_id)
            assert data["decision_id"] == str(decision_id)
            assert data["decision"] == "approved"
            assert mock_db_session.commit.called is True
            # Verify row-level lock request
            assert mock_get_gate.call_args.kwargs.get("for_update") is True
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_decide_gate_authorized_rejection_with_feedback(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """Authorized approver can reject a gate with mandatory feedback."""
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()
    gate = Gate(
        id=gate_id,
        job_id=job_id,
        gate_type="G2_CHARACTERIZATION",
        state="pending",
        artifact_versions_shown={},
        needs_human_flags=[],
    )

    decision_id = uuid.uuid4()
    gate_decision = GateDecision(
        id=decision_id,
        gate_id=gate_id,
        actor=str(principal.user_id),
        actor_user_id=principal.user_id,
        decision="rejected",
        feedback="Missing test coverage for legacy billing module.",
        decided_at=datetime.now(UTC),
    )

    with (
        patch(
            "modernization_platform.repositories.gates.GateRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=gate,
        ),
        patch(
            "modernization_platform.repositories.gates.GateRepository.record_authorized_decision",
            new_callable=AsyncMock,
            return_value=gate_decision,
        ),
        patch(
            "modernization_platform.repositories.audit_events.AuditEventRepository.append_event",
            new_callable=AsyncMock,
        ),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    f"/api/v1/jobs/{job_id}/gates/{gate_id}/decisions",
                    json={
                        "decision": "rejected",
                        "feedback": "Missing test coverage for legacy billing module.",
                    },
                )

            assert response.status_code == 200
            data = response.json()
            assert data["gate_id"] == str(gate_id)
            assert data["decision"] == "rejected"
            assert mock_db_session.commit.called is True
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_decide_gate_rejection_missing_feedback_fails_contract(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """Rejection without feedback violates contract validation (HTTP 422)."""
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/v1/jobs/{job_id}/gates/{gate_id}/decisions",
                json={"decision": "rejected"},
            )

        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_decide_gate_stale_or_non_pending_returns_conflict(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """Deciding a gate that is already approved or rejected returns 409 Conflict."""
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()
    # Gate already resolved
    stale_gate = Gate(
        id=gate_id,
        job_id=job_id,
        gate_type="G1_FEASIBILITY",
        state="approved",
        artifact_versions_shown={},
        needs_human_flags=[],
    )

    with patch(
        "modernization_platform.repositories.gates.GateRepository.get_by_id_scoped",
        new_callable=AsyncMock,
        return_value=stale_gate,
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    f"/api/v1/jobs/{job_id}/gates/{gate_id}/decisions",
                    json={"decision": "approved"},
                )

            assert response.status_code == 409
            assert "Gate is not pending" in response.json()["message"]
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_decide_gate_forbidden_for_owner_and_reviewer(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """OWNER and REVIEWER roles cannot decide gates (requires GATE_DECIDE -> HTTP 403)."""
    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()

    for forbidden_role in (Role.OWNER, Role.REVIEWER):
        principal = _principal(forbidden_role)
        app.dependency_overrides[get_current_principal] = lambda p=principal: p
        app.dependency_overrides[get_db_session] = lambda: mock_db_session

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    f"/api/v1/jobs/{job_id}/gates/{gate_id}/decisions",
                    json={"decision": "approved"},
                )

            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_decide_gate_cross_tenant_returns_404(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """If gate belongs to another tenant or job, lookup returns None resulting in 404."""
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()

    with patch(
        "modernization_platform.repositories.gates.GateRepository.get_by_id_scoped",
        new_callable=AsyncMock,
        return_value=None,
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    f"/api/v1/jobs/{job_id}/gates/{gate_id}/decisions",
                    json={"decision": "approved"},
                )

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_decide_gate_with_waivers_success(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """Approved gate decision can attach structured waivers."""
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()
    gate = Gate(
        id=gate_id,
        job_id=job_id,
        gate_type="G3_BLUEPRINT_PLAN",
        state="pending",
        artifact_versions_shown={},
        needs_human_flags=[],
    )

    decision_id = uuid.uuid4()
    gate_decision = GateDecision(
        id=decision_id,
        gate_id=gate_id,
        actor=str(principal.user_id),
        actor_user_id=principal.user_id,
        decision="approved",
        waivers={"items": [{"subject": "DB Migration", "reason": "Approved by DBA"}]},
        decided_at=datetime.now(UTC),
    )

    with (
        patch(
            "modernization_platform.repositories.gates.GateRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=gate,
        ),
        patch(
            "modernization_platform.repositories.gates.GateRepository.record_authorized_decision",
            new_callable=AsyncMock,
            return_value=gate_decision,
        ),
        patch(
            "modernization_platform.repositories.audit_events.AuditEventRepository.append_event",
            new_callable=AsyncMock,
        ),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    f"/api/v1/jobs/{job_id}/gates/{gate_id}/decisions",
                    json={
                        "decision": "approved",
                        "waivers": [{"subject": "DB Migration", "reason": "Approved by DBA"}],
                    },
                )

            assert response.status_code == 200
            data = response.json()
            assert data["gate_id"] == str(gate_id)
            assert data["decision"] == "approved"
            assert mock_db_session.commit.called is True
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_decide_gate_atomic_rollback_on_failure(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """If audit event logging fails, the transaction is rolled back cleanly."""
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()
    gate = Gate(
        id=gate_id,
        job_id=job_id,
        gate_type="G1_FEASIBILITY",
        state="pending",
        artifact_versions_shown={},
        needs_human_flags=[],
    )

    decision_id = uuid.uuid4()
    gate_decision = GateDecision(
        id=decision_id,
        gate_id=gate_id,
        actor=str(principal.user_id),
        actor_user_id=principal.user_id,
        decision="approved",
        decided_at=datetime.now(UTC),
    )

    with (
        patch(
            "modernization_platform.repositories.gates.GateRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=gate,
        ),
        patch(
            "modernization_platform.repositories.gates.GateRepository.record_authorized_decision",
            new_callable=AsyncMock,
            return_value=gate_decision,
        ),
        patch(
            "modernization_platform.repositories.audit_events.AuditEventRepository.append_event",
            side_effect=RuntimeError("Audit write failed"),
        ),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    f"/api/v1/jobs/{job_id}/gates/{gate_id}/decisions",
                    json={"decision": "approved"},
                )

            assert response.status_code == 500
            assert mock_db_session.rollback.called is True
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_job_gates_authorized(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """Authorized reviewer can list gates for their job."""
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()
    gate = Gate(
        id=gate_id,
        job_id=job_id,
        gate_type="G1_FEASIBILITY",
        state="pending",
        artifact_versions_shown={"FeasibilityReport": 1},
        needs_human_flags=[{"code": "GAP_DISCOVERED", "severity": "high"}],
        budget_used_cents=150.0,
    )

    with (
        patch(
            "modernization_platform.repositories.jobs.JobRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=MagicMock(id=job_id),
        ),
        patch(
            "modernization_platform.repositories.gates.GateRepository.list_gates_by_job_scoped",
            new_callable=AsyncMock,
            return_value=[gate],
        ),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(f"/api/v1/jobs/{job_id}/gates")

            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert data["items"][0]["gate_id"] == str(gate_id)
            assert data["items"][0]["gate_type"] == "G1_FEASIBILITY"
            assert data["items"][0]["state"] == "pending"
            assert data["items"][0]["budget_used_cents"] == 150.0
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_job_gate_authorized(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    """Authorized user can retrieve full details of a specific gate."""
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()
    gate = Gate(
        id=gate_id,
        job_id=job_id,
        gate_type="G2_CHARACTERIZATION",
        state="pending",
        artifact_versions_shown={},
        needs_human_flags=[],
    )

    with patch(
        "modernization_platform.repositories.gates.GateRepository.get_by_id_scoped",
        new_callable=AsyncMock,
        return_value=gate,
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(f"/api/v1/jobs/{job_id}/gates/{gate_id}")

            assert response.status_code == 200
            data = response.json()
            assert data["gate_id"] == str(gate_id)
            assert data["gate_type"] == "G2_CHARACTERIZATION"
            assert data["state"] == "pending"
        finally:
            app.dependency_overrides.clear()
