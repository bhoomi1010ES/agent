"""Integration tests for Audit trail API endpoints (Workstream C)."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modernization_platform.db.models.audit_event import AuditEvent
from modernization_platform.db.models.job import Job
from modernization_platform.db.session import get_db_session
from modernization_platform.security.dependencies import get_current_principal
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal


def _principal(
    role: Role = Role.OWNER,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="test-auditor",
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
async def test_get_audit_trail_success(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner="owner",
        tenant_id=principal.tenant_id,
        owner_user_id=principal.user_id,
        status="running",
        source_ref="repo@rev",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    event1 = AuditEvent(
        id=uuid.uuid4(),
        job_id=job_id,
        actor=str(principal.user_id),
        actor_user_id=principal.user_id,
        action="JOB_CREATED",
        correlation_id="corr-1",
        payload={"stage": "intake"},
        event_time=datetime.now(UTC),
        event_version=1,
    )
    event2 = AuditEvent(
        id=uuid.uuid4(),
        job_id=job_id,
        actor=str(principal.user_id),
        actor_user_id=principal.user_id,
        action="GATE_DECIDED",
        correlation_id="corr-2",
        payload={"gate": "G1", "decision": "approved"},
        event_time=datetime.now(UTC),
        event_version=1,
    )

    mock_job_res = MagicMock()
    mock_job_res.scalar_one_or_none.return_value = job

    mock_events_res = MagicMock()
    mock_events_res.scalars.return_value.all.return_value = [event1, event2]

    mock_count_res = MagicMock()
    mock_count_res.scalar.return_value = 2

    mock_db_session.execute.side_effect = [mock_job_res, mock_events_res, mock_count_res]

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{job_id}/audit?offset=0&limit=50")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["items"][0]["action"] == "JOB_CREATED"
        assert data["items"][1]["action"] == "GATE_DECIDED"
        assert data["pagination"]["total"] == 2
        assert data["pagination"]["offset"] == 0
        assert data["pagination"]["limit"] == 50
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_audit_trail_forbidden_for_reviewer(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{job_id}/audit")

        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_audit_trail_forbidden_for_approver(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    principal = _principal(Role.APPROVER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{job_id}/audit")

        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_audit_trail_cross_tenant_returns_404(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    mock_job_res = MagicMock()
    mock_job_res.scalar_one_or_none.return_value = None  # Not visible across tenant
    mock_db_session.execute.return_value = mock_job_res

    other_job_id = uuid.uuid4()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{other_job_id}/audit")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_audit_trail_unauthenticated(app: FastAPI) -> None:
    job_id = uuid.uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/api/v1/jobs/{job_id}/audit")
    assert response.status_code == 401
