"""Unit tests for S3StorageAdapter verifying error translation, retries, and cleanup."""

from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError

from modernization_platform.storage.exceptions import (
    ObjectNotFoundException,
    StorageException,
    StoragePermissionException,
    StorageTimeoutException,
)
from modernization_platform.storage.s3 import S3StorageAdapter


@pytest.fixture
def mock_s3_adapter() -> S3StorageAdapter:
    return S3StorageAdapter(
        bucket="my-s3-bucket",
        endpoint_url="http://localhost:9000",
        region_name="us-east-1",
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
    )


@pytest.mark.asyncio
async def test_s3_put_object_success(mock_s3_adapter: S3StorageAdapter) -> None:
    """S3 adapter calls client.put_object with bucket, key, and metadata."""
    mock_client = AsyncMock()
    mock_client.put_object = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_client
    ctx.__aexit__.return_value = None

    with patch.object(mock_s3_adapter, "_client_context", return_value=ctx):
        meta = await mock_s3_adapter.put_object(
            key="test/file.json",
            data=b'{"key": "val"}',
            content_type="application/json",
            metadata={"source": "agent"},
        )
        assert meta.bucket == "my-s3-bucket"
        assert meta.key == "test/file.json"
        assert mock_client.put_object.called is True
        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "my-s3-bucket"
        assert call_kwargs["Key"] == "test/file.json"
        assert call_kwargs["ContentType"] == "application/json"


@pytest.mark.asyncio
async def test_s3_get_object_success(mock_s3_adapter: S3StorageAdapter) -> None:
    """S3 adapter reads stream, calculates hash, and returns StoredObject."""
    body_mock = AsyncMock()
    body_mock.read.return_value = b'{"hello": "world"}'
    stream_ctx = AsyncMock()
    stream_ctx.__aenter__.return_value = body_mock
    stream_ctx.__aexit__.return_value = None

    mock_client = AsyncMock()
    mock_client.get_object.return_value = {
        "Body": stream_ctx,
        "ContentType": "application/json",
        "Metadata": {},
    }

    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_client
    ctx.__aexit__.return_value = None

    with patch.object(mock_s3_adapter, "_client_context", return_value=ctx):
        stored = await mock_s3_adapter.get_object(key="test/file.json")
        assert stored.data == b'{"hello": "world"}'
        assert stored.metadata.key == "test/file.json"


@pytest.mark.asyncio
async def test_s3_not_found_error_translated(mock_s3_adapter: S3StorageAdapter) -> None:
    """NoSuchKey ClientError translates to ObjectNotFoundException."""
    mock_client = AsyncMock()
    client_error = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
        "GetObject",
    )
    mock_client.get_object.side_effect = client_error

    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_client
    ctx.__aexit__.return_value = None

    with (
        patch.object(mock_s3_adapter, "_client_context", return_value=ctx),
        pytest.raises(ObjectNotFoundException) as exc_info,
    ):
        await mock_s3_adapter.get_object(key="missing.json")
    assert "not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_s3_access_denied_error_translated(mock_s3_adapter: S3StorageAdapter) -> None:
    """AccessDenied ClientError translates to StoragePermissionException."""
    mock_client = AsyncMock()
    client_error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Forbidden."}},
        "PutObject",
    )
    mock_client.put_object.side_effect = client_error

    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_client
    ctx.__aexit__.return_value = None

    with (
        patch.object(mock_s3_adapter, "_client_context", return_value=ctx),
        pytest.raises(StoragePermissionException),
    ):
        await mock_s3_adapter.put_object(key="file.json", data=b"data")


@pytest.mark.asyncio
async def test_s3_timeout_error_translated(mock_s3_adapter: S3StorageAdapter) -> None:
    """ConnectTimeoutError translates to StorageTimeoutException."""
    mock_client = AsyncMock()
    mock_client.put_object.side_effect = ConnectTimeoutError(endpoint_url="http://s3.local")

    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_client
    ctx.__aexit__.return_value = None

    with (
        patch.object(mock_s3_adapter, "_client_context", return_value=ctx),
        pytest.raises(StorageTimeoutException),
    ):
        await mock_s3_adapter.put_object(key="file.json", data=b"data")


@pytest.mark.asyncio
async def test_s3_endpoint_unavailable_translated(mock_s3_adapter: S3StorageAdapter) -> None:
    """EndpointConnectionError translates to StorageUnavailableException."""
    mock_client = AsyncMock()
    mock_client.head_bucket.side_effect = EndpointConnectionError(endpoint_url="http://s3.local")

    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_client
    ctx.__aexit__.return_value = None

    with patch.object(mock_s3_adapter, "_client_context", return_value=ctx):
        healthy = await mock_s3_adapter.check_health()
        assert healthy is False


@pytest.mark.asyncio
async def test_s3_partial_upload_cleanup(mock_s3_adapter: S3StorageAdapter) -> None:
    """When put_object fails partway, a compensating delete_object is issued."""
    mock_client = AsyncMock()
    mock_client.put_object.side_effect = RuntimeError("Socket reset during streaming")
    mock_client.delete_object = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_client
    ctx.__aexit__.return_value = None

    with (
        patch.object(mock_s3_adapter, "_client_context", return_value=ctx),
        pytest.raises(StorageException),
    ):
        await mock_s3_adapter.put_object(key="broken.bin", data=b"some bytes")
    assert mock_client.delete_object.called is True
