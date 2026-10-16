"""Live FastAPI verification tests for Human Gates and Append-Only Decisions."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.db.models.job import Job
from modernization_platform.db.session import get_db_session
from modernization_platform.domain.gates.states import GateDecisionType, GateState
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
async def test_health_endpoints(app: FastAPI) -> None:
    """Verify live and ready health endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res_live = await client.get("/health/live")
        assert res_live.status_code == 200

        res_ready = await client.get("/health/ready")
        assert res_ready.status_code in (200, 503)


@pytest.mark.asyncio
async def test_gate_api_creation_and_retrieval(
    app: FastAPI, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify gate creation and retrieval through FastAPI endpoints."""
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()

    job = Job(
        id=job_id,
        tenant_id=principal.tenant_id,
        owner_user_id=principal.user_id,
        owner="test-owner",
        status="awaiting_approval",
        version=1,
        source_ref="git@github.com:legacy/cobol.git",
        target_stack_spec={"framework": "FastAPI"},
        budget={},
    )
    gate = Gate(
        id=gate_id,
        job_id=job_id,
        gate_type="G1_FEASIBILITY",
        state=GateState.PENDING.value,
        requested_at=datetime.now(UTC),
        artifact_versions_shown={"spec": 1},
        needs_human_flags=[],
        budget_used_cents=100.0,
        decisions=[],
    )

    from modernization_platform.repositories.gates import GateRepository
    from modernization_platform.repositories.jobs import JobRepository

    monkeypatch.setattr(JobRepository, "get_by_id_scoped", AsyncMock(return_value=job))
    monkeypatch.setattr(GateRepository, "create_gate", AsyncMock(return_value=gate))
    monkeypatch.setattr(GateRepository, "get_by_id_scoped", AsyncMock(return_value=gate))
    monkeypatch.setattr(GateRepository, "list_decisions_for_gate", AsyncMock(return_value=[]))

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Create gate
            create_res = await client.post(
                f"/api/v1/jobs/{job_id}/gates",
                json={
                    "gate_type": "G1_FEASIBILITY",
                    "timeout_seconds": 3600,
                    "artifact_versions_shown": {"spec": 1},
                },
            )
            assert create_res.status_code == 201
            data = create_res.json()
            assert data["gate_id"] == str(gate_id)
            assert data["state"] == "pending"

            # Retrieve gate
            get_res = await client.get(f"/api/v1/gates/{gate_id}")
            assert get_res.status_code == 200
            assert get_res.json()["gate_id"] == str(gate_id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_gate_api_approval_and_rejection(
    app: FastAPI, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify approval, rejection, and decision recording via REST API."""
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    mock_res = MagicMock()
    mock_res.scalar.return_value = 2
    mock_db_session.execute.return_value = mock_res

    job_id = uuid.uuid4()
    gate_id = uuid.uuid4()

    gate = Gate(
        id=gate_id,
        job_id=job_id,
        gate_type="G2_CHARACTERIZATION",
        state=GateState.PENDING.value,
        requested_at=datetime.now(UTC),
        artifact_versions_shown={"spec": 2},
        decisions=[],
    )

    dec_approved = GateDecision(
        id=uuid.uuid4(),
        gate_id=gate_id,
        job_id=job_id,
        gate_type="G2_CHARACTERIZATION",
        actor=principal.subject,
        actor_user_id=principal.user_id,
        approver_role="approver",
        decision=GateDecisionType.APPROVED.value,
        feedback="Verified characterization models",
        decided_at=datetime.now(UTC),
    )

    from modernization_platform.repositories.gates import GateRepository

    monkeypatch.setattr(GateRepository, "get_by_id_scoped", AsyncMock(return_value=gate))
    monkeypatch.setattr(
        GateRepository, "record_authorized_decision", AsyncMock(return_value=dec_approved)
    )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Rejection with blank reason should be rejected with 422 or 400
            reject_blank = await client.post(
                f"/api/v1/gates/{gate_id}/reject",
                json={"reason": "   "},
            )
            assert reject_blank.status_code in (400, 422)

            # Approval succeeds
            approve_res = await client.post(
                f"/api/v1/gates/{gate_id}/approve",
                json={
                    "reason": "Verified characterization models",
                    "artifact_versions": {"spec": 2},
                },
            )
            assert approve_res.status_code == 200
            assert approve_res.json()["decision"] == "approved"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_gate_api_authorization_failure(app: FastAPI, mock_db_session: AsyncMock) -> None:
    """Non-approver role is forbidden from deciding gates."""
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    gate_id = uuid.uuid4()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                f"/api/v1/gates/{gate_id}/approve",
                json={"reason": "Unauthorized attempt"},
            )
            assert res.status_code == 403
    finally:
        app.dependency_overrides.clear()
