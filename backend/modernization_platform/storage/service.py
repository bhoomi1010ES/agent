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
