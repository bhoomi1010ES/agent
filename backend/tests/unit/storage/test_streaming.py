"""Unit tests for streaming uploads, streaming downloads, and multipart threshold bounds."""

import hashlib
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from modernization_platform.storage.exceptions import (
    ChecksumMismatchException,
    ObjectNotFoundException,
    OversizedArtifactException,
    StorageException,
)
from modernization_platform.storage.memory import MemoryStorageAdapter
from modernization_platform.storage.s3 import S3StorageAdapter


async def _async_chunks(data: bytes, chunk_size: int = 1024) -> AsyncIterator[bytes]:
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


@pytest.mark.asyncio
async def test_memory_adapter_stream_upload_and_download() -> None:
    """Verify streaming upload and download with accurate on-the-fly hashing in memory adapter."""
    adapter = MemoryStorageAdapter(bucket="test-bucket", max_artifact_size_bytes=100_000)
    key = "artifacts/test-tenant/test-job/snapshot/v1_content.bin"
    payload = b"Modernization platform binary chunk 1 " * 50
    expected_hash = hashlib.sha256(payload).hexdigest()

    meta = await adapter.stream_upload(
        key=key,
        content_stream=_async_chunks(payload, chunk_size=64),
        content_type="application/octet-stream",
        expected_hash=expected_hash,
        expected_size=len(payload),
    )

    assert meta.key == key
    assert meta.bucket == "test-bucket"
    assert meta.size_bytes == len(payload)
    assert meta.content_hash == expected_hash

    # Verify head and existence
    assert await adapter.object_exists(key) is True
    head_meta = await adapter.head_object(key=key)
    assert head_meta is not None
    assert head_meta.content_hash == expected_hash

    # Stream download
    dl_meta, stream = await adapter.stream_download(
        key, chunk_size=128, expected_hash=expected_hash
    )
    assert dl_meta.size_bytes == len(payload)

    downloaded = bytearray()
    async for chunk in stream:
        downloaded.extend(chunk)

    assert bytes(downloaded) == payload


@pytest.mark.asyncio
async def test_memory_adapter_stream_upload_oversized_raises() -> None:
    """Stream upload exceeding max artifact size raises OversizedArtifactException."""
    adapter = MemoryStorageAdapter(bucket="test-bucket", max_artifact_size_bytes=500)
    key = "artifacts/oversized.bin"
    large_payload = b"X" * 1000

    with pytest.raises(OversizedArtifactException):
        await adapter.stream_upload(
            key=key,
            content_stream=_async_chunks(large_payload, chunk_size=200),
        )

    # Object should not exist after failed upload
    assert await adapter.object_exists(key) is False


@pytest.mark.asyncio
async def test_memory_adapter_stream_upload_checksum_mismatch() -> None:
    """Stream upload with mismatched expected hash raises ChecksumMismatchException."""
    adapter = MemoryStorageAdapter(bucket="test-bucket", max_artifact_size_bytes=100_000)
    key = "artifacts/corrupt.bin"
    payload = b"Some legitimate bytes"
    wrong_hash = "0" * 64

    with pytest.raises(ChecksumMismatchException):
        await adapter.stream_upload(
            key=key,
            content_stream=_async_chunks(payload),
            expected_hash=wrong_hash,
        )

    assert await adapter.object_exists(key) is False


@pytest.mark.asyncio
async def test_memory_adapter_stream_download_corrupted_content() -> None:
    """Stream download verifying hash raises ChecksumMismatchException on tampered content."""
    adapter = MemoryStorageAdapter(bucket="test-bucket")
    key = "artifacts/tampered.bin"
    payload = b"Original bytes"
    correct_hash = hashlib.sha256(payload).hexdigest()

    await adapter.put_object(key=key, data=payload)

    # Tamper with storage content directly
    stored_meta, _ = adapter._store[key]
    adapter._store[key] = (stored_meta, b"Tampered bytes")

    with pytest.raises(ChecksumMismatchException):
        _dl_meta, stream = await adapter.stream_download(key, expected_hash=correct_hash)
        async for _chunk in stream:
            pass


@pytest.mark.asyncio
async def test_memory_adapter_stream_download_missing_object() -> None:
    """Stream download of non-existent key raises ObjectNotFoundException."""
    adapter = MemoryStorageAdapter(bucket="test-bucket")
    with pytest.raises(ObjectNotFoundException):
        await adapter.stream_download("artifacts/does_not_exist.bin")


@pytest.mark.asyncio
async def test_s3_adapter_multipart_upload_workflow() -> None:
    """S3 adapter executes multipart upload when payload exceeds multipart_threshold."""
    adapter = S3StorageAdapter(
        bucket="prod-bucket",
        endpoint_url="https://s3.amazonaws.com",
        region_name="us-east-1",
        access_key_id="test-key",
        secret_access_key="test-secret",
        multipart_threshold=100,  # low threshold for unit testing
        multipart_chunk_size=50,
    )

    mock_client = AsyncMock()
    mock_client.create_multipart_upload.return_value = {"UploadId": "up-12345"}
    mock_client.upload_part.side_effect = [
        {"ETag": '"etag-1"'},
        {"ETag": '"etag-2"'},
        {"ETag": '"etag-3"'},
    ]
    mock_client.complete_multipart_upload.return_value = {}

    payload = b"A" * 150
    key = "artifacts/tenant-1/job-1/snapshot/v1_content.bin"

    with patch.object(adapter, "_client_context") as mock_ctx:
        mock_ctx.return_value.__aenter__.return_value = mock_client
        meta = await adapter.stream_upload(
            key=key,
            content_stream=_async_chunks(payload, chunk_size=50),
        )

        assert meta.key == key
        assert meta.bucket == "prod-bucket"
        assert meta.size_bytes == 150
        mock_client.create_multipart_upload.assert_called_once()
        assert mock_client.upload_part.call_count == 3
        mock_client.complete_multipart_upload.assert_called_once()


@pytest.mark.asyncio
async def test_s3_adapter_multipart_upload_aborts_on_failure() -> None:
    """S3 adapter aborts multipart upload if part upload fails."""
    adapter = S3StorageAdapter(
        bucket="prod-bucket",
        endpoint_url="https://s3.amazonaws.com",
        region_name="us-east-1",
        access_key_id="test-key",
        secret_access_key="test-secret",
        multipart_threshold=100,
        multipart_chunk_size=50,
    )

    mock_client = AsyncMock()
    mock_client.create_multipart_upload.return_value = {"UploadId": "up-99999"}
    mock_client.upload_part.side_effect = RuntimeError("Network dropped during part 2")
    mock_client.abort_multipart_upload.return_value = {}

    payload = b"B" * 150
    key = "artifacts/failed_multipart.bin"

    with patch.object(adapter, "_client_context") as mock_ctx:
        mock_ctx.return_value.__aenter__.return_value = mock_client
        with pytest.raises(StorageException):
            await adapter.stream_upload(
                key=key,
                content_stream=_async_chunks(payload, chunk_size=50),
            )

        mock_client.abort_multipart_upload.assert_called_once_with(
            Bucket="prod-bucket",
            Key=key,
            UploadId="up-99999",
        )
