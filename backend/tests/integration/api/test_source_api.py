"""Integration API tests for Job source ingestion and provenance endpoints."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modernization_platform.db.models.source_provenance import SourceProvenanceRecord
from modernization_platform.db.session import get_db_session
from modernization_platform.integrations.git.models import (
    RepositoryMetadata,
    SourceProvenance,
)
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
async def test_ingest_source_api_success(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    job_id = uuid.uuid4()
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    commit_sha = "4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345"
    tree_hash = "1111111122222222333333334444444455555555"
    fake_provenance = SourceProvenance(
        job_id=job_id,
        repository_url="https://github.com/acme/legacy.git",
        provider="git",
        requested_ref="main",
        resolved_commit_sha=commit_sha,
        branch="main",
        tree_hash=tree_hash,
        commit_author="Alice Dev",
        commit_author_email="alice@example.com",
        commit_timestamp=datetime.now(UTC),
        commit_message="Initial commit",
        repository_metadata=RepositoryMetadata(
            default_branch="main",
            size_bytes=4096,
            file_count=8,
            commit_author="Alice Dev",
            tree_hash=tree_hash,
        ),
        ingestion_timestamp=datetime.now(UTC),
        ingestion_id=uuid.uuid4(),
        ingestion_status="completed",
        provenance_hash="abcdef0123456789" * 4,
    )

    try:
        with patch(
            "modernization_platform.services.source_ingestion.SourceIngestionService.ingest_source",
            AsyncMock(return_value=fake_provenance),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    f"/api/v1/jobs/{job_id}/source/ingest",
                    json={
                        "ref_override": "main",
                        "git_token": "ghp_mock_token_12345",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["job_id"] == str(job_id)
                assert data["resolved_commit_sha"] == commit_sha
                assert data["file_count"] == 8
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_provenance_api_success_and_not_found(
    app: FastAPI,
    mock_db_session: AsyncMock,
) -> None:
    principal = _principal(Role.OWNER)
    job_id = uuid.uuid4()
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    fake_record = SourceProvenanceRecord(
        id=uuid.uuid4(),
        job_id=job_id,
        tenant_id=principal.tenant_id,
        repository_url="https://github.com/acme/legacy.git",
        provider="git",
        requested_ref="main",
        resolved_commit_sha="4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345",
        branch="main",
        tree_hash="1111111122222222333333334444444455555555",
        commit_author="Alice Dev",
        commit_author_email="alice@example.com",
        commit_timestamp=datetime.now(UTC),
        commit_message="Initial commit",
        file_count=8,
        size_bytes=4096,
        repository_metadata={},
        provenance_hash="abcdef0123456789" * 4,
        ingestion_status="completed",
        ingested_at=datetime.now(UTC),
    )

    try:
        # 1. Found
        with patch(
            "modernization_platform.services.source_ingestion.SourceIngestionService.get_provenance",
            AsyncMock(return_value=fake_record),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(f"/api/v1/jobs/{job_id}/source/provenance")
                assert response.status_code == 200
                data = response.json()
                assert data["resolved_commit_sha"] == "4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345"

        # 2. Not found
        with patch(
            "modernization_platform.services.source_ingestion.SourceIngestionService.get_provenance",
            AsyncMock(return_value=None),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(f"/api/v1/jobs/{job_id}/source/provenance")
                assert response.status_code == 404
                assert response.json()["code"] == "SOURCE_PROVENANCE_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_module_branch_api(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    job_id = uuid.uuid4()
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    expected_branch = f"job/{job_id}/payment-gateway"

    try:
        with patch(
            "modernization_platform.services.source_ingestion.SourceIngestionService.create_module_workspace",
            AsyncMock(return_value=expected_branch),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    f"/api/v1/jobs/{job_id}/source/branches",
                    json={"module": "payment-gateway"},
                )
                assert response.status_code == 201
                data = response.json()
                assert data["branch_name"] == expected_branch
                assert data["module"] == "payment-gateway"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cleanup_job_workspace_api(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    job_id = uuid.uuid4()
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    try:
        with patch(
            "modernization_platform.services.source_ingestion.SourceIngestionService.cleanup_job_workspace",
            AsyncMock(return_value=None),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.delete(f"/api/v1/jobs/{job_id}/source/workspace")
                assert response.status_code == 204
    finally:
        app.dependency_overrides.clear()
