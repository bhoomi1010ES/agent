"""Integration tests for Job lifecycle API endpoints (Workstream B)."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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
        subject="test-architect",
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
async def test_create_job_success(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/jobs",
                json={
                    "source_repository": "https://github.com/acme/legacy-monolith",
                    "source_revision": "v1.2.3",
                    "target_stack": {
                        "language": "python",
                        "framework": "fastapi",
                        "database": "postgresql",
                    },
                    "budget": {
                        "max_cost_cents": 50000,
                        "max_repair_attempts": 3,
                    },
                },
                headers={"X-Correlation-ID": "corr-create-001"},
            )

        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert "created_at" in data

        # Verify session operations
        assert mock_db_session.add.call_count >= 2  # Job and JobMember
        mock_db_session.commit.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_job_unauthenticated(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/jobs",
            json={
                "source_repository": "https://github.com/acme/legacy-monolith",
                "source_revision": "v1.0",
                "target_stack": {"language": "python"},
                "budget": {"max_cost_cents": 10000},
            },
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_job_forbidden_for_reviewer(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/jobs",
                json={
                    "source_repository": "https://github.com/acme/legacy-monolith",
                    "source_revision": "v1.0",
                    "target_stack": {"language": "python"},
                    "budget": {"max_cost_cents": 10000},
                },
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_job_rejects_client_assigned_scope(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/jobs",
                json={
                    "source_repository": "https://github.com/acme/legacy-monolith",
                    "source_revision": "v1.0",
                    "target_stack": {"language": "python"},
                    "budget": {"max_cost_cents": 10000},
                    "tenant_id": str(uuid.uuid4()),  # Forged tenant
                    "owner_user_id": str(uuid.uuid4()),  # Forged owner
                },
            )
        assert response.status_code == 422  # Extra fields rejected by TransportRequest
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_job_rejects_invalid_budget(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/jobs",
                json={
                    "source_repository": "https://github.com/acme/legacy-monolith",
                    "source_revision": "v1.0",
                    "target_stack": {"language": "python"},
                    "budget": {"max_cost_cents": -500},  # Invalid negative budget
                },
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_jobs_success(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job = Job(
        id=uuid.uuid4(),
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="pending",
        source_ref="https://github.com/acme/legacy@main",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
    )

    mock_res_jobs = MagicMock()
    mock_res_jobs.scalars.return_value.all.return_value = [job]
    mock_res_count = MagicMock()
    mock_res_count.scalar.return_value = 1
    mock_db_session.execute.side_effect = [mock_res_jobs, mock_res_count]

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/v1/jobs?offset=0&limit=10&status=pending")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["job_id"] == str(job.id)
        assert data["items"][0]["status"] == "pending"
        assert data["pagination"]["total"] == 1
        assert data["pagination"]["offset"] == 0
        assert data["pagination"]["limit"] == 10
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_job_detail_success(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="running",
        source_ref="https://github.com/acme/legacy@v2",
        target_stack_spec={"language": "python", "framework": "fastapi"},
        budget={"max_cost_cents": 75000},
    )

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = job
    mock_db_session.execute.return_value = mock_res

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == str(job_id)
        assert data["status"] == "running"
        assert data["tenant_id"] == str(principal.tenant_id)
        assert data["owner_user_id"] == str(principal.user_id)
        assert data["target_stack_spec"]["language"] == "python"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_job_detail_cross_tenant_returns_404(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    # Scoped query returns None when tenant does not match
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_res

    other_job_id = uuid.uuid4()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{other_job_id}")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
