"""In-memory storage adapter for deterministic, isolated unit and integration testing."""

import logging
from datetime import UTC, datetime

from modernization_platform.core.decorators import log_errors
from modernization_platform.storage.base import StorageAdapter
from modernization_platform.storage.exceptions import (
    ObjectNotFoundException,
    StorageException,
    StoragePartialUploadException,
    StoragePermissionException,
    StorageTimeoutException,
    StorageUnavailableException,
)
from modernization_platform.storage.keys import build_storage_uri
from modernization_platform.storage.models import StorageMetadata, StoredObject

logger = logging.getLogger(__name__)


class MemoryStorageAdapter(StorageAdapter):
    """In-memory object storage adapter with full contract fidelity and fault injection."""

    def __init__(
        self,
        bucket: str = "test-artifacts",
        max_artifact_size_bytes: int = 52_428_800,
    ) -> None:
        super().__init__(bucket=bucket, max_artifact_size_bytes=max_artifact_size_bytes)
        self._store: dict[str, tuple[StorageMetadata, bytes]] = {}
        # Fault injection hooks for negative testing
        self.simulate_timeout: bool = False
        self.simulate_permission_denied: bool = False
        self.simulate_unavailable: bool = False
        self.simulate_partial_upload_failure: bool = False
        self.cleaned_up_keys: list[str] = []

    def _check_fault_injection(self, key: str | None = None) -> None:
        """Evaluate active fault simulation conditions."""
        try:
            if self.simulate_unavailable:
                raise StorageUnavailableException("Simulated storage service unavailable.")
            if self.simulate_timeout:
                raise StorageTimeoutException("Simulated storage provider timeout.")
            if self.simulate_permission_denied:
                raise StoragePermissionException("Simulated storage access denied.")
            if self.simulate_partial_upload_failure:
                raise StoragePartialUploadException("Simulated partial upload failure.", key=key)
        except StorageException:
            raise
        except Exception as exc:
            logger.exception("_check_fault_injection failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def _do_put(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        content_hash: str,
        metadata: dict[str, str],
    ) -> StorageMetadata:
        try:
            self._check_fault_injection(key=key)

            storage_ref = build_storage_uri(self.bucket, key)
            now = datetime.now(UTC)
            meta = StorageMetadata(
                key=key,
                bucket=self.bucket,
                size_bytes=len(data),
                content_hash=content_hash,
                content_type=content_type,
                created_at=now,
                storage_ref=storage_ref,
                custom_metadata=metadata,
            )
            self._store[key] = (meta, data)
            return meta
        except Exception as exc:
            logger.exception(
                "MemoryStorageAdapter._do_put failed | key=%s | %s: %s",
                key,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def _do_get(self, *, key: str) -> StoredObject:
        try:
            self._check_fault_injection(key=key)

            if key not in self._store:
                raise ObjectNotFoundException(
                    f"Object with key '{key}' not found in bucket '{self.bucket}'.",
                    key=key,
                )
            meta, data = self._store[key]
            return StoredObject(metadata=meta, data=data)
        except Exception as exc:
            logger.exception(
                "MemoryStorageAdapter._do_get failed | key=%s | %s: %s",
                key,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def _do_head(self, *, key: str) -> StorageMetadata | None:
        try:
            self._check_fault_injection(key=key)

            if key not in self._store:
                return None
            meta, _ = self._store[key]
            return meta
        except Exception as exc:
            logger.exception(
                "MemoryStorageAdapter._do_head failed | key=%s | %s: %s",
                key,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def _do_delete(self, *, key: str) -> bool:
        try:
            self._check_fault_injection(key=key)

            self.cleaned_up_keys.append(key)
            if key in self._store:
                del self._store[key]
                return True
            return False
        except Exception as exc:
            logger.exception(
                "MemoryStorageAdapter._do_delete failed | key=%s | %s: %s",
                key,
                type(exc).__name__,
                exc,
            )
            raise

    @log_errors
    async def check_health(self) -> bool:
        try:
            self._check_fault_injection()
            return True
        except Exception:
            return False

    @log_errors
    async def close(self) -> None:
        try:
            self._store.clear()
        except Exception as exc:
            logger.exception("MemoryStorageAdapter.close failed | %s: %s", type(exc).__name__, exc)
            raise


__all__ = ["MemoryStorageAdapter"]
