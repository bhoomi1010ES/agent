"""Unit tests for StorageAdapter base validation and MemoryStorageAdapter."""

import hashlib

import pytest

from modernization_platform.storage.exceptions import (
    ChecksumMismatchException,
    EmptyArtifactException,
    ObjectNotFoundException,
    OversizedArtifactException,
    StoragePartialUploadException,
    StoragePermissionException,
    StorageTimeoutException,
    StorageUnavailableException,
)
from modernization_platform.storage.memory import MemoryStorageAdapter


@pytest.fixture
def memory_adapter() -> MemoryStorageAdapter:
    return MemoryStorageAdapter(bucket="test-bucket", max_artifact_size_bytes=1024)


@pytest.mark.asyncio
async def test_put_and_get_success(memory_adapter: MemoryStorageAdapter) -> None:
    """Store and retrieve an object successfully with content-hash verification."""
    data = b'{"module": "auth", "status": "active"}'
    expected_hash = hashlib.sha256(data).hexdigest()
    key = "artifacts/job-1/report.json"

    meta = await memory_adapter.put_object(
        key=key,
        data=data,
        content_type="application/json",
        expected_hash=expected_hash,
        metadata={"author": "architect"},
    )
    assert meta.key == key
    assert meta.bucket == "test-bucket"
    assert meta.size_bytes == len(data)
    assert meta.content_hash == expected_hash
    assert meta.storage_ref == f"s3://test-bucket/{key}"

    stored = await memory_adapter.get_object(key=key, expected_hash=expected_hash)
    assert stored.data == data
    assert stored.metadata.content_hash == expected_hash
    assert stored.metadata.custom_metadata.get("author") == "architect"


@pytest.mark.asyncio
async def test_put_empty_artifact_rejected(memory_adapter: MemoryStorageAdapter) -> None:
    """Zero-byte artifact payloads are strictly rejected."""
    with pytest.raises(EmptyArtifactException) as exc_info:
        await memory_adapter.put_object(key="empty.json", data=b"")
    assert "cannot be empty" in str(exc_info.value)


@pytest.mark.asyncio
async def test_put_oversized_artifact_rejected(memory_adapter: MemoryStorageAdapter) -> None:
    """Payloads exceeding maximum configured size are rejected with 413 error."""
    large_data = b"x" * 2048  # limit is 1024
    with pytest.raises(OversizedArtifactException) as exc_info:
        await memory_adapter.put_object(key="large.bin", data=large_data)
    assert "exceeds maximum limit" in str(exc_info.value)


@pytest.mark.asyncio
async def test_put_checksum_mismatch_rejected(memory_adapter: MemoryStorageAdapter) -> None:
    """If caller claims a hash that does not match data bytes, upload fails."""
    data = b"hello world"
    wrong_hash = "0" * 64
    with pytest.raises(ChecksumMismatchException) as exc_info:
        await memory_adapter.put_object(key="test.json", data=data, expected_hash=wrong_hash)
    assert "does not match payload digest" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_checksum_mismatch_rejected(memory_adapter: MemoryStorageAdapter) -> None:
    """If retrieved bytes do not match expected hash, retrieval fails."""
    data = b"original data"
    key = "test_item.json"
    await memory_adapter.put_object(key=key, data=data)

    wrong_hash = "1" * 64
    with pytest.raises(ChecksumMismatchException) as exc_info:
        await memory_adapter.get_object(key=key, expected_hash=wrong_hash)
    assert "does not match expected hash" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_missing_object_raises_404(memory_adapter: MemoryStorageAdapter) -> None:
    """Querying a missing key raises ObjectNotFoundException."""
    with pytest.raises(ObjectNotFoundException) as exc_info:
        await memory_adapter.get_object(key="nonexistent/key.json")
    assert "not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_head_and_delete_object(memory_adapter: MemoryStorageAdapter) -> None:
    """Head returns metadata or None; delete removes object cleanly."""
    data = b"some data"
    key = "artifacts/temp.json"
    assert await memory_adapter.head_object(key=key) is None

    await memory_adapter.put_object(key=key, data=data)
    meta = await memory_adapter.head_object(key=key)
    assert meta is not None
    assert meta.key == key

    deleted = await memory_adapter.delete_object(key=key)
    assert deleted is True
    assert await memory_adapter.head_object(key=key) is None

    deleted_again = await memory_adapter.delete_object(key=key)
    assert deleted_again is False


@pytest.mark.asyncio
async def test_fault_simulation_timeout(memory_adapter: MemoryStorageAdapter) -> None:
    """Simulated timeout triggers StorageTimeoutException."""
    memory_adapter.simulate_timeout = True
    with pytest.raises(StorageTimeoutException):
        await memory_adapter.put_object(key="item.json", data=b"data")


@pytest.mark.asyncio
async def test_fault_simulation_permission_denied(memory_adapter: MemoryStorageAdapter) -> None:
    """Simulated permission error triggers StoragePermissionException."""
    memory_adapter.simulate_permission_denied = True
    with pytest.raises(StoragePermissionException):
        await memory_adapter.get_object(key="item.json")


@pytest.mark.asyncio
async def test_fault_simulation_unavailable(memory_adapter: MemoryStorageAdapter) -> None:
    """Simulated provider outage triggers StorageUnavailableException."""
    memory_adapter.simulate_unavailable = True
    assert await memory_adapter.check_health() is False
    with pytest.raises(StorageUnavailableException):
        await memory_adapter.put_object(key="item.json", data=b"data")


@pytest.mark.asyncio
async def test_fault_simulation_partial_upload_failure(
    memory_adapter: MemoryStorageAdapter,
) -> None:
    """Simulated interrupted upload raises StoragePartialUploadException."""
    memory_adapter.simulate_partial_upload_failure = True
    with pytest.raises(StoragePartialUploadException):
        await memory_adapter.put_object(key="item.json", data=b"data")
