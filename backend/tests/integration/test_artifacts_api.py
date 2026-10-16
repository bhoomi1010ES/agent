"""Integration tests for Artifact retrieval API endpoints (Workstream C)."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modernization_platform.db.models.artifact import Artifact
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
        subject="test-engineer",
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
async def test_list_artifacts_success(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.REVIEWER)
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

    art1 = Artifact(
        id=uuid.uuid4(),
        job_id=job_id,
        type="FeasibilityReport",
        version=1,
        content_hash="sha256:111111",
        storage_ref="s3://evidence/feasibility_v1.json",
        artifact_metadata={"schema_version": "1.0.0"},
        created_at=datetime.now(UTC),
    )
    art2 = Artifact(
        id=uuid.uuid4(),
        job_id=job_id,
        type="TargetBlueprint",
        version=1,
        content_hash="sha256:222222",
        storage_ref="s3://evidence/blueprint_v1.json",
        artifact_metadata={"schema_version": "1.0.0"},
        created_at=datetime.now(UTC),
    )

    # First query: get_job in AuthorizationService
    mock_job_res = MagicMock()
    mock_job_res.scalar_one_or_none.return_value = job
    # Second query: list_artifacts_scoped
    mock_art_res = MagicMock()
    mock_art_res.scalars.return_value.all.return_value = [art1, art2]

    mock_db_session.execute.side_effect = [mock_job_res, mock_art_res]

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{job_id}/artifacts")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        types = {item["artifact_type"] for item in data["items"]}
        assert types == {"FeasibilityReport", "TargetBlueprint"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_artifact_by_type_latest(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.REVIEWER)
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

    art = Artifact(
        id=uuid.uuid4(),
        job_id=job_id,
        type="FeasibilityReport",
        version=2,
        content_hash="sha256:latest_hash",
        storage_ref="s3://evidence/feasibility_v2.json",
        artifact_metadata={"schema_version": "1.0.0"},
        created_at=datetime.now(UTC),
    )

    mock_job_res = MagicMock()
    mock_job_res.scalar_one_or_none.return_value = job
    mock_art_res = MagicMock()
    mock_art_res.scalar_one_or_none.return_value = art

    mock_db_session.execute.side_effect = [mock_job_res, mock_art_res]

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{job_id}/artifacts/FeasibilityReport")

        assert response.status_code == 200
        data = response.json()
        assert data["artifact_type"] == "FeasibilityReport"
        assert data["version"] == 2
        assert data["content_hash"] == "sha256:latest_hash"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_artifact_by_type_version_not_found(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    principal = _principal(Role.REVIEWER)
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

    mock_job_res = MagicMock()
    mock_job_res.scalar_one_or_none.return_value = job
    mock_art_res = MagicMock()
    mock_art_res.scalar_one_or_none.return_value = None

    mock_db_session.execute.side_effect = [mock_job_res, mock_art_res]

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                f"/api/v1/jobs/{job_id}/artifacts/EquivalenceReport?version=99"
            )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_artifacts_cross_tenant_returns_404(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    # Scoped query returns None when job belongs to another tenant
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_res

    other_job_id = uuid.uuid4()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{other_job_id}/artifacts")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
