"""Integration tests for artifact content retrieval endpoint (Workstream C1)."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.job import Job
from modernization_platform.db.session import get_db_session
from modernization_platform.security.dependencies import get_current_principal
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.storage.exceptions import (
    ChecksumMismatchException,
    ObjectNotFoundException,
    StorageTimeoutException,
)
from modernization_platform.storage.models import StorageMetadata, StoredObject


def _principal(
    role: Role = Role.REVIEWER,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="test-reviewer",
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
async def test_get_artifact_content_success(app: FastAPI, mock_db_session: AsyncMock) -> None:
    """Authorized reviewer can download artifact raw JSON content."""
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    job = Job(id=job_id, tenant_id=principal.tenant_id, owner="owner", status="active")

    content_bytes = b'{"repository_id": "acme/legacy", "file_inventory": ["main.py"]}'
    content_hash = "a" * 64
    storage_ref = "s3://modernization-artifacts/artifacts/item.json"

    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job_id,
        type="RepoInventory",
        version=1,
        content_hash=content_hash,
        storage_ref=storage_ref,
        created_at=datetime.now(UTC),
    )

    metadata = StorageMetadata(
        key="artifacts/item.json",
        bucket="modernization-artifacts",
        size_bytes=len(content_bytes),
        content_hash=content_hash,
        content_type="application/json",
        created_at=datetime.now(UTC),
        storage_ref=storage_ref,
    )
    stored_object = StoredObject(metadata=metadata, data=content_bytes)

    with (
        patch(
            "modernization_platform.repositories.jobs.JobRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch(
            "modernization_platform.repositories.artifacts.ArtifactRepository.get_by_job_and_type_scoped",
            new_callable=AsyncMock,
            return_value=artifact,
        ),
        patch(
            "modernization_platform.storage.service.ArtifactStorageService.retrieve_artifact",
            new_callable=AsyncMock,
            return_value=stored_object,
        ),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(
                    f"/api/v1/jobs/{job_id}/artifacts/RepoInventory/content"
                )

            assert response.status_code == 200
            assert response.headers["content-type"] == "application/json"
            assert response.headers["etag"] == f'"{content_hash}"'
            assert response.content == content_bytes
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_artifact_content_missing_storage_object_returns_404(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    """When DB record exists but underlying object is missing, returns 404 OBJECT_NOT_FOUND."""
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    job = Job(id=job_id, tenant_id=principal.tenant_id, owner="owner", status="active")
    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job_id,
        type="RepoInventory",
        version=1,
        content_hash="0" * 64,
        storage_ref="s3://modernization-artifacts/missing.json",
    )

    with (
        patch(
            "modernization_platform.repositories.jobs.JobRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch(
            "modernization_platform.repositories.artifacts.ArtifactRepository.get_by_job_and_type_scoped",
            new_callable=AsyncMock,
            return_value=artifact,
        ),
        patch(
            "modernization_platform.storage.service.ArtifactStorageService.retrieve_artifact",
            new_callable=AsyncMock,
            side_effect=ObjectNotFoundException("Storage object missing.", key="missing.json"),
        ),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(
                    f"/api/v1/jobs/{job_id}/artifacts/RepoInventory/content"
                )

            assert response.status_code == 404
            assert response.json()["code"] == "OBJECT_NOT_FOUND"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_artifact_content_checksum_mismatch_returns_422(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    """Corrupted storage content returns 422 CHECKSUM_MISMATCH."""
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    job = Job(id=job_id, tenant_id=principal.tenant_id, owner="owner", status="active")
    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job_id,
        type="RepoInventory",
        version=1,
        content_hash="a" * 64,
        storage_ref="s3://modernization-artifacts/item.json",
    )

    with (
        patch(
            "modernization_platform.repositories.jobs.JobRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch(
            "modernization_platform.repositories.artifacts.ArtifactRepository.get_by_job_and_type_scoped",
            new_callable=AsyncMock,
            return_value=artifact,
        ),
        patch(
            "modernization_platform.storage.service.ArtifactStorageService.retrieve_artifact",
            new_callable=AsyncMock,
            side_effect=ChecksumMismatchException("Digest mismatch."),
        ),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(
                    f"/api/v1/jobs/{job_id}/artifacts/RepoInventory/content"
                )

            assert response.status_code == 422
            assert response.json()["code"] == "CHECKSUM_MISMATCH"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_artifact_content_storage_timeout_returns_504(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    """Storage timeout returns 504 STORAGE_TIMEOUT."""
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    job = Job(id=job_id, tenant_id=principal.tenant_id, owner="owner", status="active")
    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job_id,
        type="RepoInventory",
        version=1,
        content_hash="a" * 64,
        storage_ref="s3://modernization-artifacts/item.json",
    )

    with (
        patch(
            "modernization_platform.repositories.jobs.JobRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch(
            "modernization_platform.repositories.artifacts.ArtifactRepository.get_by_job_and_type_scoped",
            new_callable=AsyncMock,
            return_value=artifact,
        ),
        patch(
            "modernization_platform.storage.service.ArtifactStorageService.retrieve_artifact",
            new_callable=AsyncMock,
            side_effect=StorageTimeoutException("S3 read timed out."),
        ),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(
                    f"/api/v1/jobs/{job_id}/artifacts/RepoInventory/content"
                )

            assert response.status_code == 504
            assert response.json()["code"] == "STORAGE_TIMEOUT"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_artifact_content_cross_tenant_returns_404(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    """Cross-tenant artifact content retrieval returns 404 Not Found."""
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()

    with patch(
        "modernization_platform.repositories.jobs.JobRepository.get_by_id_scoped",
        new_callable=AsyncMock,
        return_value=None,
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(
                    f"/api/v1/jobs/{job_id}/artifacts/RepoInventory/content"
                )

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
