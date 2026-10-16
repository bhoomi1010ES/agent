"""Abstract base storage adapter with built-in validation, size checking, and hashing."""

import hashlib
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from modernization_platform.core.decorators import log_errors
from modernization_platform.storage.exceptions import (
    ChecksumMismatchException,
    EmptyArtifactException,
    OversizedArtifactException,
)
from modernization_platform.storage.keys import validate_storage_key, validate_storage_metadata
from modernization_platform.storage.models import StorageMetadata, StoredObject

logger = logging.getLogger(__name__)


class StorageAdapter(ABC):
    """Abstract interface defining required capabilities for S3-compatible object storage."""

    def __init__(
        self,
        bucket: str,
        max_artifact_size_bytes: int = 52_428_800,
    ) -> None:
        self.bucket = bucket
        self.max_artifact_size_bytes = max_artifact_size_bytes

    @log_errors
    async def put_object(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str = "application/json",
        expected_hash: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StorageMetadata:
        """Store an artifact payload after validating key, size, and content hash."""
        try:
            validated_key = validate_storage_key(key)
            validated_metadata = validate_storage_metadata(metadata)

            if len(data) == 0:
                raise EmptyArtifactException("Artifact payload cannot be empty (0 bytes).")

            if len(data) > self.max_artifact_size_bytes:
                raise OversizedArtifactException(
                    f"Artifact payload ({len(data)} bytes) exceeds maximum limit of "
                    f"{self.max_artifact_size_bytes} bytes.",
                    size_bytes=len(data),
                    max_bytes=self.max_artifact_size_bytes,
                )

            actual_hash = hashlib.sha256(data).hexdigest()
            if expected_hash is not None and expected_hash.lower() != actual_hash.lower():
                raise ChecksumMismatchException(
                    f"Claimed content hash ({expected_hash}) does not match payload digest ({actual_hash}).",
                    expected_hash=expected_hash,
                    actual_hash=actual_hash,
                )

            return await self._do_put(
                key=validated_key,
                data=data,
                content_type=content_type,
                content_hash=actual_hash,
                metadata=validated_metadata,
            )
        except Exception as exc:
            logger.exception(
                "StorageAdapter.put_object failed | key=%s | %s: %s", key, type(exc).__name__, exc
            )
            raise

    @log_errors
    async def get_object(
        self,
        *,
        key: str,
        expected_hash: str | None = None,
    ) -> StoredObject:
        """Retrieve an object by key and verify content integrity using SHA-256."""
        try:
            validated_key = validate_storage_key(key)
            stored = await self._do_get(key=validated_key)

            actual_hash = hashlib.sha256(stored.data).hexdigest()
            if expected_hash is not None and expected_hash.lower() != actual_hash.lower():
                raise ChecksumMismatchException(
                    f"Retrieved content digest ({actual_hash}) does not match expected hash ({expected_hash}).",
                    expected_hash=expected_hash,
                    actual_hash=actual_hash,
                )
            if stored.metadata.content_hash.lower() != actual_hash.lower():
                raise ChecksumMismatchException(
                    f"Stored metadata content hash ({stored.metadata.content_hash}) does not match bytes ({actual_hash}).",
                    expected_hash=stored.metadata.content_hash,
                    actual_hash=actual_hash,
                )

            return stored
        except Exception as exc:
            logger.exception(
                "StorageAdapter.get_object failed | key=%s | %s: %s", key, type(exc).__name__, exc
            )
            raise

    @log_errors
    async def head_object(self, *, key: str) -> StorageMetadata | None:
        """Return metadata for an object if present, or None if not found."""
        try:
            validated_key = validate_storage_key(key)
            return await self._do_head(key=validated_key)
        except Exception as exc:
            logger.exception(
                "StorageAdapter.head_object failed | key=%s | %s: %s", key, type(exc).__name__, exc
            )
            raise

    @log_errors
    async def delete_object(self, *, key: str) -> bool:
        """Delete an object by key."""
        try:
            validated_key = validate_storage_key(key)
            return await self._do_delete(key=validated_key)
        except Exception as exc:
            logger.exception(
                "StorageAdapter.delete_object failed | key=%s | %s: %s",
                key,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def object_exists(self, key: str) -> bool:
        """Check whether an object exists at the specified key."""
        try:
            meta = await self.head_object(key=key)
            return meta is not None
        except Exception as exc:
            logger.exception("StorageAdapter.object_exists failed | key=%s: %s", key, exc)
            return False

    @log_errors
    async def stream_upload(
        self,
        key: str,
        *,
        content_stream: AsyncIterator[bytes],
        content_type: str = "application/octet-stream",
        expected_hash: str | None = None,
        expected_size: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StorageMetadata:
        """Stream an artifact payload into storage, computing SHA-256 and enforcing limits."""
        try:
            validated_key = validate_storage_key(key)
            validated_metadata = validate_storage_metadata(metadata)
            return await self._do_stream_upload(
                key=validated_key,
                content_stream=content_stream,
                content_type=content_type,
                expected_hash=expected_hash,
                expected_size=expected_size,
                metadata=validated_metadata,
            )
        except Exception as exc:
            logger.exception(
                "StorageAdapter.stream_upload failed | key=%s | %s: %s",
                key,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def stream_download(
        self,
        key: str,
        *,
        chunk_size: int = 65536,
        expected_hash: str | None = None,
    ) -> tuple[StorageMetadata, AsyncIterator[bytes]]:
        """Stream an artifact payload from storage with on-the-fly SHA-256 verification."""
        try:
            validated_key = validate_storage_key(key)
            return await self._do_stream_download(
                key=validated_key,
                chunk_size=chunk_size,
                expected_hash=expected_hash,
            )
        except Exception as exc:
            logger.exception(
                "StorageAdapter.stream_download failed | key=%s | %s: %s",
                key,
                type(exc).__name__,
                exc,
            )
            raise

    @abstractmethod
    async def _do_put(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        content_hash: str,
        metadata: dict[str, str],
    ) -> StorageMetadata:
        """Provider-specific put implementation."""

    @abstractmethod
    async def _do_get(self, *, key: str) -> StoredObject:
        """Provider-specific get implementation."""

    @abstractmethod
    async def _do_head(self, *, key: str) -> StorageMetadata | None:
        """Provider-specific head implementation."""

    @abstractmethod
    async def _do_delete(self, *, key: str) -> bool:
        """Provider-specific delete implementation."""

    @abstractmethod
    async def _do_stream_upload(
        self,
        *,
        key: str,
        content_stream: AsyncIterator[bytes],
        content_type: str,
        expected_hash: str | None,
        expected_size: int | None,
        metadata: dict[str, str],
    ) -> StorageMetadata:
        """Provider-specific streaming upload implementation."""

    @abstractmethod
    async def _do_stream_download(
        self,
        *,
        key: str,
        chunk_size: int,
        expected_hash: str | None,
    ) -> tuple[StorageMetadata, AsyncIterator[bytes]]:
        """Provider-specific streaming download implementation."""

    @abstractmethod
    async def check_health(self) -> bool:
        """Verify provider availability and bucket accessibility."""

    @abstractmethod
    async def close(self) -> None:
        """Close underlying client sessions and network pools."""


__all__ = ["StorageAdapter"]
