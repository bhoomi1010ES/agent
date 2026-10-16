"""Unit tests for ArtifactStorageService canonicalization, hashing, and bucket safety."""

import uuid

import pytest

from modernization_platform.schemas.agent_artifacts.models import RepoInventory
from modernization_platform.storage.exceptions import InvalidStorageKeyException
from modernization_platform.storage.memory import MemoryStorageAdapter
from modernization_platform.storage.service import ArtifactStorageService
from tests.contract.factories import repo_inventory_payload


@pytest.fixture
def memory_adapter() -> MemoryStorageAdapter:
    return MemoryStorageAdapter(bucket="artifacts-bucket")


@pytest.fixture
def storage_service(memory_adapter: MemoryStorageAdapter) -> ArtifactStorageService:
    return ArtifactStorageService(adapter=memory_adapter)


@pytest.mark.asyncio
async def test_store_and_retrieve_pydantic_artifact(
    storage_service: ArtifactStorageService,
) -> None:
    """ArtifactStorageService canonicalizes Pydantic model and verifies SHA-256."""
    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    model = RepoInventory.model_validate(repo_inventory_payload())

    storage_ref, content_hash, meta = await storage_service.store_artifact(
        tenant_id=tenant_id,
        job_id=job_id,
        artifact_type="RepoInventory",
        payload=model,
    )
    assert storage_ref.startswith("s3://artifacts-bucket/artifacts/")
    assert meta.content_hash == content_hash

    stored = await storage_service.retrieve_artifact(
        storage_ref=storage_ref, expected_hash=content_hash
    )
    assert stored.metadata.content_hash == content_hash
    assert b"legacy-repo" in stored.data


@pytest.mark.asyncio
async def test_store_and_retrieve_dict_artifact(storage_service: ArtifactStorageService) -> None:
    """ArtifactStorageService stores and retrieves raw dictionary canonically."""
    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    data = {"status": "analyzed", "findings_count": 5}

    storage_ref, content_hash, _meta = await storage_service.store_artifact(
        tenant_id=tenant_id,
        job_id=job_id,
        artifact_type="FeasibilityReport",
        payload=data,
    )
    assert storage_ref.startswith("s3://artifacts-bucket/artifacts/")

    stored = await storage_service.retrieve_artifact(
        storage_ref=storage_ref, expected_hash=content_hash
    )
    assert stored.data == b'{"findings_count":5,"status":"analyzed"}'


@pytest.mark.asyncio
async def test_retrieve_arbitrary_bucket_rejected(storage_service: ArtifactStorageService) -> None:
    """Requesting an object from an unauthorized or unmanaged bucket is rejected."""
    unauthorized_uri = "s3://other-tenant-bucket/artifacts/job-1/report.json"
    with pytest.raises(InvalidStorageKeyException) as exc_info:
        await storage_service.retrieve_artifact(storage_ref=unauthorized_uri)
    assert "does not match configured application bucket" in str(exc_info.value)


@pytest.mark.asyncio
async def test_artifact_exists_and_delete(storage_service: ArtifactStorageService) -> None:
    """Existence check and deletion operate correctly."""
    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    storage_ref, _, _ = await storage_service.store_artifact(
        tenant_id=tenant_id,
        job_id=job_id,
        artifact_type="RepoInventory",
        payload={"a": 1},
    )

    assert await storage_service.artifact_exists(storage_ref=storage_ref) is True

    deleted = await storage_service.delete_artifact(storage_ref=storage_ref)
    assert deleted is True
    assert await storage_service.artifact_exists(storage_ref=storage_ref) is False
