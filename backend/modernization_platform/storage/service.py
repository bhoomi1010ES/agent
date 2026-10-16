"""High-level artifact storage service enforcing canonicalization, hashing, and safety."""

import hashlib
import json
import logging
import uuid
from typing import Any

from pydantic import BaseModel

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.validation import canonical_json_bytes
from modernization_platform.storage.base import StorageAdapter
from modernization_platform.storage.exceptions import InvalidStorageKeyException
from modernization_platform.storage.factory import get_storage_adapter
from modernization_platform.storage.keys import (
    build_artifact_storage_key,
    parse_storage_uri,
)
from modernization_platform.storage.models import StorageMetadata, StoredObject

logger = logging.getLogger(__name__)


class ArtifactStorageService:
    """Service orchestrating content-addressed artifact storage and secure retrieval."""

    def __init__(self, adapter: StorageAdapter | None = None) -> None:
        self._adapter = adapter or get_storage_adapter()

    @log_errors
    async def store_artifact(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        artifact_type: str,
        payload: BaseModel | dict[str, Any] | bytes | str,
        schema_version: str = "1.0.0",
        version: int | None = None,
    ) -> tuple[str, str, StorageMetadata]:
        """Canonicalize, hash, and persist artifact content into object storage.

        Returns:
            Tuple of (storage_ref, content_hash, storage_metadata).
        """
        try:
            if isinstance(payload, BaseModel):
                data = canonical_json_bytes(payload)
            elif isinstance(payload, dict):
                # RFC 8259 sort-keys compact utf-8
                data = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            elif isinstance(payload, str):
                data = payload.encode("utf-8")
            elif isinstance(payload, bytes):
                data = payload
            else:
                raise ValueError(f"Unsupported artifact payload type: {type(payload).__name__}")

            content_hash = hashlib.sha256(data).hexdigest()
            key = build_artifact_storage_key(
                tenant_id=tenant_id,
                job_id=job_id,
                artifact_type=artifact_type,
                content_hash=content_hash,
                version=version,
            )

            metadata = {
                "artifact-type": artifact_type,
                "schema-version": schema_version,
            }

            meta = await self._adapter.put_object(
                key=key,
                data=data,
                content_type="application/json",
                expected_hash=content_hash,
                metadata=metadata,
            )
            return meta.storage_ref, content_hash, meta
        except Exception as exc:
            logger.exception(
                "ArtifactStorageService.store_artifact failed | job_id=%s type=%s | %s: %s",
                job_id,
                artifact_type,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def retrieve_artifact(
        self,
        *,
        storage_ref: str,
        expected_hash: str | None = None,
    ) -> StoredObject:
        """Retrieve artifact content by storage URI with integrity verification and bucket bounds."""
        try:
            bucket, key = parse_storage_uri(storage_ref)
            # Prevent arbitrary bucket access from forged or unmanaged URIs
            if bucket != self._adapter.bucket:
                raise InvalidStorageKeyException(
                    f"Storage bucket '{bucket}' in reference does not match configured application bucket.",
                    key=key,
                )

            return await self._adapter.get_object(key=key, expected_hash=expected_hash)
        except Exception as exc:
            logger.exception(
                "ArtifactStorageService.retrieve_artifact failed | storage_ref=%s | %s: %s",
                storage_ref,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def stream_store_artifact(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        artifact_type: str,
        content_stream: Any,
        content_type: str = "application/octet-stream",
        schema_version: str = "1.0.0",
        version: int | None = None,
        artifact_id: uuid.UUID | None = None,
        expected_hash: str | None = None,
        expected_size: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StorageMetadata:
        """Stream an artifact into object storage with chunked upload, hashing, and size validation."""
        try:
            key = build_artifact_storage_key(
                tenant_id=tenant_id,
                job_id=job_id,
                artifact_type=artifact_type,
                content_hash=expected_hash,
                version=version,
                artifact_id=artifact_id,
            )

            user_meta = dict(metadata or {})
            user_meta.setdefault("artifact-type", artifact_type)
            user_meta.setdefault("schema-version", schema_version)

            return await self._adapter.stream_upload(
                key=key,
                content_stream=content_stream,
                content_type=content_type,
                expected_hash=expected_hash,
                expected_size=expected_size,
                metadata=user_meta,
            )
        except Exception as exc:
            logger.exception(
                "ArtifactStorageService.stream_store_artifact failed | job_id=%s type=%s | %s: %s",
                job_id,
                artifact_type,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def stream_retrieve_artifact(
        self,
        *,
        storage_ref: str,
        expected_hash: str | None = None,
        chunk_size: int = 65_536,
    ) -> tuple[StorageMetadata, Any]:
        """Stream artifact content from storage with on-the-fly hash verification."""
        try:
            bucket, key = parse_storage_uri(storage_ref)
            if bucket != self._adapter.bucket:
                raise InvalidStorageKeyException(
                    f"Storage bucket '{bucket}' in reference does not match configured application bucket.",
                    key=key,
                )
            return await self._adapter.stream_download(
                key=key,
                chunk_size=chunk_size,
                expected_hash=expected_hash,
            )
        except Exception as exc:
            logger.exception(
                "ArtifactStorageService.stream_retrieve_artifact failed | storage_ref=%s | %s: %s",
                storage_ref,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def verify_artifact_integrity(
        self,
        *,
        storage_ref: str,
        expected_hash: str,
        expected_size: int | None = None,
    ) -> bool:
        """Explicitly verify that the object exists and its byte hash matches expected_hash."""
        try:
            bucket, key = parse_storage_uri(storage_ref)
            if bucket != self._adapter.bucket:
                raise InvalidStorageKeyException(
                    f"Storage bucket '{bucket}' in reference does not match configured application bucket.",
                    key=key,
                )

            meta = await self._adapter.head_object(key=key)
            if meta is None:
                from modernization_platform.storage.exceptions import ObjectNotFoundException

                raise ObjectNotFoundException(
                    f"Object at '{storage_ref}' does not exist in storage.",
                    key=key,
                )

            if expected_size is not None and meta.size_bytes != expected_size:
                from modernization_platform.storage.exceptions import ChecksumMismatchException

                raise ChecksumMismatchException(
                    f"Object size mismatch: expected {expected_size} bytes, got {meta.size_bytes} bytes."
                )

            # Read stream to calculate full SHA-256 hash and verify
            _download_meta, stream = await self._adapter.stream_download(
                key=key,
                expected_hash=expected_hash,
            )
            async for _chunk in stream:
                pass

            return True
        except Exception as exc:
            logger.exception(
                "ArtifactStorageService.verify_artifact_integrity failed | storage_ref=%s | %s: %s",
                storage_ref,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def delete_artifact(self, *, storage_ref: str) -> bool:
        """Delete underlying storage object for a given storage URI."""
        try:
            bucket, key = parse_storage_uri(storage_ref)
            if bucket != self._adapter.bucket:
                raise InvalidStorageKeyException(
                    f"Storage bucket '{bucket}' in reference does not match configured application bucket.",
                    key=key,
                )
            return await self._adapter.delete_object(key=key)
        except Exception as exc:
            logger.exception(
                "ArtifactStorageService.delete_artifact failed | storage_ref=%s | %s: %s",
                storage_ref,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def artifact_exists(self, *, storage_ref: str) -> bool:
        """Check if an object exists at the specified storage reference."""
        try:
            bucket, key = parse_storage_uri(storage_ref)
            if bucket != self._adapter.bucket:
                return False
            meta = await self._adapter.head_object(key=key)
            return meta is not None
        except Exception as exc:
            logger.exception(
                "ArtifactStorageService.artifact_exists failed | storage_ref=%s | %s: %s",
                storage_ref,
                type(exc).__name__,
                exc,
            )
            return False


__all__ = ["ArtifactStorageService"]
