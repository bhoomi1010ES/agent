"""Integration tests for artifact storage lifecycle, streaming, integrity, lineage, and retention."""

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.identity import (
    JobMember,
    Tenant,
    TenantMembership,
    UserAccount,
)
from modernization_platform.db.models.job import Job
from modernization_platform.db.session import get_db_session
from modernization_platform.security.dependencies import get_current_principal
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.storage.exceptions import (
    ChecksumMismatchException,
    ObjectNotFoundException,
)
from modernization_platform.storage.models import StorageMetadata


async def _setup_principal(
    session: AsyncSession,
    role: Role = Role.OWNER,
    subject: str = "test-engineer",
) -> AuthenticatedPrincipal:
    tenant = Tenant(
        slug=f"tenant-{uuid.uuid4().hex[:8]}",
        display_name=f"Tenant {uuid.uuid4().hex[:8]}",
        active=True,
    )
    session.add(tenant)
    await session.flush()

    user = UserAccount(
        issuer="https://auth.modernization.internal",
        subject=subject,
        display_name=subject,
        active=True,
    )
    session.add(user)
    await session.flush()

    membership = TenantMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        role=role.value,
        active=True,
    )
    session.add(membership)
    await session.flush()

    return AuthenticatedPrincipal(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership.id,
        session_id=uuid.uuid4(),
        subject=subject,
        issuer=user.issuer,
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


async def _create_test_job(
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    status: str = "completed",
) -> Job:
    job = Job(
        id=uuid.uuid4(),
        owner=str(principal.user_id),
        tenant_id=principal.tenant_id,
        owner_user_id=principal.user_id,
        status=status,
        source_ref="repo@rev",
    )
    session.add(job)
    await session.flush()

    job_member = JobMember(job_id=job.id, membership_id=principal.membership_id)
    session.add(job_member)
    await session.flush()

    return job


@pytest.mark.asyncio
async def test_get_artifact_detail_success(app: FastAPI, db_session: AsyncSession) -> None:
    """Authorized reviewer can retrieve authoritative artifact metadata including status, size, and content type."""
    principal = await _setup_principal(db_session, Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    try:
        job = await _create_test_job(db_session, principal, status="completed")

        artifact_id = uuid.uuid4()
        artifact = Artifact(
            id=artifact_id,
            job_id=job.id,
            type="RepoInventory",
            version=1,
            content_hash="a" * 64,
            storage_ref="s3://modernization-artifacts/artifacts/item.json",
            status="available",
            size_bytes=1024,
            content_type="application/json",
            derived_from=[],
            artifact_metadata={"schema_version": "1.0.0"},
            created_at=datetime.now(UTC),
        )
        db_session.add(artifact)
        await db_session.flush()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(f"/api/v1/artifacts/{artifact_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == str(artifact_id)
        assert data["job_id"] == str(job.id)
        assert data["status"] == "available"
        assert data["size_bytes"] == 1024
        assert data["content_type"] == "application/json"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cross_tenant_artifact_isolation_returns_404(
    app: FastAPI, db_session: AsyncSession
) -> None:
    """Artifact belonging to Tenant A cannot be viewed or accessed by Tenant B."""
    tenant_a_principal = await _setup_principal(db_session, Role.OWNER, subject="tenant-a-user")
    tenant_b_principal = await _setup_principal(db_session, Role.OWNER, subject="tenant-b-user")

    job_a = await _create_test_job(db_session, tenant_a_principal, status="completed")

    artifact_a = Artifact(
        id=uuid.uuid4(),
        job_id=job_a.id,
        type="RepoInventory",
        version=1,
        content_hash="b" * 64,
        storage_ref="s3://modernization-artifacts/tenant_a_item.json",
        status="available",
    )
    db_session.add(artifact_a)
    await db_session.flush()

    app.dependency_overrides[get_current_principal] = lambda: tenant_b_principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(f"/api/v1/artifacts/{artifact_a.id}")

        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_artifact_content_download_and_integrity(
    app: FastAPI, db_session: AsyncSession
) -> None:
    """Stream download returns raw binary chunks with ETag and Content-Length."""
    principal = await _setup_principal(db_session, Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    payload = b"Modernization binary payload bytes for streaming test"
    content_hash = hashlib.sha256(payload).hexdigest()
    storage_ref = "s3://modernization-artifacts/stream_item.bin"

    job = await _create_test_job(db_session, principal, status="completed")

    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="ArchiveSnapshot",
        version=1,
        content_hash=content_hash,
        storage_ref=storage_ref,
        status="available",
        size_bytes=len(payload),
        content_type="application/octet-stream",
    )
    db_session.add(artifact)
    await db_session.flush()

    meta = StorageMetadata(
        key="stream_item.bin",
        bucket="modernization-artifacts",
        size_bytes=len(payload),
        content_hash=content_hash,
        content_type="application/octet-stream",
        created_at=datetime.now(UTC),
        storage_ref=storage_ref,
    )

    async def _mock_stream() -> AsyncIterator[bytes]:
        yield payload[:20]
        yield payload[20:]

    with patch(
        "modernization_platform.storage.service.ArtifactStorageService.stream_retrieve_artifact",
        new_callable=AsyncMock,
        return_value=(meta, _mock_stream()),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.get(f"/api/v1/artifacts/{artifact.id}/content")

            assert resp.status_code == 200
            assert resp.content == payload
            assert resp.headers["etag"] == f'"{content_hash}"'
            assert resp.headers["content-length"] == str(len(payload))
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_artifact_content_missing_object_returns_404(
    app: FastAPI, db_session: AsyncSession
) -> None:
    """When PostgreSQL metadata exists but object storage is missing the object, returns 404."""
    principal = await _setup_principal(db_session, Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    job = await _create_test_job(db_session, principal, status="completed")

    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="ArchiveSnapshot",
        version=1,
        content_hash="c" * 64,
        storage_ref="s3://modernization-artifacts/missing.bin",
    )
    db_session.add(artifact)
    await db_session.flush()

    with patch(
        "modernization_platform.storage.service.ArtifactStorageService.stream_retrieve_artifact",
        new_callable=AsyncMock,
        side_effect=ObjectNotFoundException("Underlying object missing", key="missing.bin"),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.get(f"/api/v1/artifacts/{artifact.id}/content")

            assert resp.status_code == 404
            assert resp.json()["code"] == "OBJECT_NOT_FOUND"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_verify_artifact_integrity_endpoint(app: FastAPI, db_session: AsyncSession) -> None:
    """Cryptographic integrity verification compares object bytes with PostgreSQL content_hash."""
    principal = await _setup_principal(db_session, Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    job = await _create_test_job(db_session, principal, status="completed")

    content_hash = "d" * 64
    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="TargetBlueprint",
        version=1,
        content_hash=content_hash,
        storage_ref="s3://modernization-artifacts/blueprint.json",
        size_bytes=512,
    )
    db_session.add(artifact)
    await db_session.flush()

    # Success scenario
    with patch(
        "modernization_platform.storage.service.ArtifactStorageService.verify_artifact_integrity",
        new_callable=AsyncMock,
        return_value=True,
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.post(f"/api/v1/artifacts/{artifact.id}/verify")

            assert resp.status_code == 200
            data = resp.json()
            assert data["verified"] is True
            assert data["content_hash"] == content_hash
            assert data["size_bytes"] == 512
        finally:
            app.dependency_overrides.clear()

    # Tampered / Corrupted scenario
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session
    with patch(
        "modernization_platform.storage.service.ArtifactStorageService.verify_artifact_integrity",
        new_callable=AsyncMock,
        side_effect=ChecksumMismatchException("Computed SHA-256 does not match authoritative hash"),
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                corrupt_resp = await client.post(f"/api/v1/artifacts/{artifact.id}/verify")

            assert corrupt_resp.status_code == 422
            assert corrupt_resp.json()["code"] == "CHECKSUM_MISMATCH"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_artifact_lineage_graph_endpoint(app: FastAPI, db_session: AsyncSession) -> None:
    """Artifact lineage graph returns direct parent and child artifacts."""
    principal = await _setup_principal(db_session, Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    job = await _create_test_job(db_session, principal, status="completed")

    parent_art = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="RepoInventory",
        version=1,
        content_hash="1" * 64,
        storage_ref="s3://modernization-artifacts/parent.json",
    )
    db_session.add(parent_art)

    current_art = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="ConversionPlan",
        version=1,
        content_hash="2" * 64,
        storage_ref="s3://modernization-artifacts/current.json",
        derived_from=[str(parent_art.id)],
    )
    db_session.add(current_art)

    child_art = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="ChangeSet",
        version=1,
        content_hash="3" * 64,
        storage_ref="s3://modernization-artifacts/child.json",
        derived_from=[str(current_art.id)],
    )
    db_session.add(child_art)
    await db_session.flush()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(f"/api/v1/artifacts/{current_art.id}/lineage")

        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == str(current_art.id)
        assert len(data["parents"]) == 1
        assert data["parents"][0]["artifact_id"] == str(parent_art.id)
        assert len(data["children"]) == 1
        assert data["children"][0]["artifact_id"] == str(child_art.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_retention_deletion_active_job_rejected(
    app: FastAPI, db_session: AsyncSession
) -> None:
    """Artifact deletion is strictly rejected if its job is in an active state."""
    principal = await _setup_principal(db_session, Role.ADMIN)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    job = await _create_test_job(db_session, principal, status="running")  # Active!

    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="RepoInventory",
        version=1,
        content_hash="e" * 64,
        storage_ref="s3://modernization-artifacts/active_job_art.json",
    )
    db_session.add(artifact)
    await db_session.flush()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.delete(f"/api/v1/artifacts/{artifact.id}")

        assert resp.status_code == 409
        assert resp.json()["code"] == "ACTIVE_JOB_ARTIFACT_PROTECTION"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_retential_integrity_deletion_rejected(
    app: FastAPI, db_session: AsyncSession
) -> None:
    """Artifact deletion is rejected if another artifact depends on it in lineage."""
    principal = await _setup_principal(db_session, Role.ADMIN)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    job = await _create_test_job(db_session, principal, status="completed")  # Terminal

    parent_art = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="RepoInventory",
        version=1,
        content_hash="f" * 64,
        storage_ref="s3://modernization-artifacts/parent_art.json",
    )
    db_session.add(parent_art)

    child_art = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="TargetBlueprint",
        version=1,
        content_hash="0" * 64,
        storage_ref="s3://modernization-artifacts/child_art.json",
        derived_from=[str(parent_art.id)],
    )
    db_session.add(child_art)
    await db_session.flush()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.delete(f"/api/v1/artifacts/{parent_art.id}")

        assert resp.status_code == 409
        assert resp.json()["code"] == "ARTIFACT_REFERENTIAL_INTEGRITY_VIOLATION"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_safe_retention_deletion_succeeds(app: FastAPI, db_session: AsyncSession) -> None:
    """Artifact deletion succeeds when job is completed and no downstream dependents exist."""
    principal = await _setup_principal(db_session, Role.ADMIN)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    job = await _create_test_job(db_session, principal, status="completed")

    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="RepoInventory",
        version=1,
        content_hash="9" * 64,
        storage_ref="s3://modernization-artifacts/deletable.json",
    )
    db_session.add(artifact)
    await db_session.flush()

    with patch(
        "modernization_platform.storage.service.ArtifactStorageService.delete_artifact",
        new_callable=AsyncMock,
        return_value=True,
    ):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.delete(f"/api/v1/artifacts/{artifact.id}")

            assert resp.status_code == 200
            assert resp.json()["deleted"] is True
        finally:
            app.dependency_overrides.clear()
