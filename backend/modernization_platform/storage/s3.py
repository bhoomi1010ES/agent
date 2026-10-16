"""S3-compatible asynchronous storage adapter for AWS S3 and MinIO."""

import asyncio
import contextlib
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

import aioboto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from modernization_platform.core.decorators import log_errors
from modernization_platform.storage.base import StorageAdapter
from modernization_platform.storage.exceptions import (
    ObjectNotFoundException,
    OversizedArtifactException,
    StorageException,
    StoragePermissionException,
    StorageTimeoutException,
    StorageUnavailableException,
)
from modernization_platform.storage.keys import build_storage_uri
from modernization_platform.storage.models import StorageMetadata, StoredObject

logger = logging.getLogger(__name__)


class S3StorageAdapter(StorageAdapter):
    """Production S3-compatible asynchronous storage adapter using aioboto3."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        use_ssl: bool = False,
        max_artifact_size_bytes: int = 52_428_800,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(bucket=bucket, max_artifact_size_bytes=max_artifact_size_bytes)
        self.endpoint_url = endpoint_url
        self.region_name = region_name
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.use_ssl = use_ssl
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

        self._session = aioboto3.Session(
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region_name,
        )
        self._botocore_config = Config(
            connect_timeout=timeout_seconds,
            read_timeout=timeout_seconds,
            retries={"max_attempts": max_retries, "mode": "adaptive"},
            s3={"addressing_style": "path"},
        )

    def _client_context(self) -> Any:
        """Create an S3 client async context manager."""
        try:
            return self._session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                use_ssl=self.use_ssl,
                config=self._botocore_config,
            )
        except Exception as exc:
            logger.exception(
                "S3StorageAdapter._client_context failed | %s: %s", type(exc).__name__, exc
            )
            raise

    def _translate_error(
        self, operation: str, exc: Exception, key: str | None = None
    ) -> StorageException:
        """Translate AWS/botocore exceptions to platform typed storage exceptions."""
        try:
            if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError, asyncio.TimeoutError)):
                return StorageTimeoutException(
                    f"S3 {operation} timed out after {self.timeout_seconds}s."
                )
            if isinstance(exc, EndpointConnectionError):
                return StorageUnavailableException(f"S3 endpoint unreachable during {operation}.")
            if isinstance(exc, ClientError):
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code in {"NoSuchKey", "404", "NotFound"}:
                    return ObjectNotFoundException(
                        f"Object '{key}' not found in bucket '{self.bucket}'.", key=key
                    )
                if error_code in {"AccessDenied", "403"}:
                    return StoragePermissionException(
                        f"Access denied to bucket '{self.bucket}' during {operation}."
                    )
                if error_code == "EntityTooLarge":
                    return OversizedArtifactException(
                        f"Artifact exceeds S3 maximum object size during {operation}."
                    )
                return StorageException(f"S3 {operation} failed: {error_code} - {exc}")
            return StorageException(f"Unexpected storage error during {operation}: {exc}")
        except Exception as inner_exc:
            logger.exception(
                "_translate_error failed | %s: %s", type(inner_exc).__name__, inner_exc
            )
            return StorageException(f"Storage error during {operation}: {exc}")

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
            custom_meta = {**metadata, "content-hash": content_hash}
            async with self._client_context() as client:
                try:
                    await client.put_object(
                        Bucket=self.bucket,
                        Key=key,
                        Body=data,
                        ContentType=content_type,
                        Metadata=custom_meta,
                    )
                except Exception as put_exc:
                    # Best-effort cleanup on partial/interrupted upload failure
                    with contextlib.suppress(Exception):
                        await client.delete_object(Bucket=self.bucket, Key=key)
                    raise self._translate_error("put_object", put_exc, key=key) from put_exc

            now = datetime.now(UTC)
            storage_ref = build_storage_uri(self.bucket, key)
            return StorageMetadata(
                key=key,
                bucket=self.bucket,
                size_bytes=len(data),
                content_hash=content_hash,
                content_type=content_type,
                created_at=now,
                storage_ref=storage_ref,
                custom_metadata=metadata,
            )
        except StorageException:
            raise
        except Exception as exc:
            logger.exception(
                "S3StorageAdapter._do_put failed | key=%s | %s: %s", key, type(exc).__name__, exc
            )
            raise self._translate_error("put_object", exc, key=key) from exc

    @log_errors
    async def _do_get(self, *, key: str) -> StoredObject:
        try:
            async with self._client_context() as client:
                try:
                    response = await client.get_object(Bucket=self.bucket, Key=key)
                    async with response["Body"] as stream:
                        data = await stream.read()
                except Exception as get_exc:
                    raise self._translate_error("get_object", get_exc, key=key) from get_exc

            meta_dict = response.get("Metadata", {})
            content_type = response.get("ContentType", "application/json")
            last_modified = response.get("LastModified", datetime.now(UTC))
            content_hash = meta_dict.get("content-hash") or hashlib.sha256(data).hexdigest()
            storage_ref = build_storage_uri(self.bucket, key)

            metadata = StorageMetadata(
                key=key,
                bucket=self.bucket,
                size_bytes=len(data),
                content_hash=content_hash,
                content_type=content_type,
                created_at=last_modified,
                storage_ref=storage_ref,
                custom_metadata={k: v for k, v in meta_dict.items() if k != "content-hash"},
            )
            return StoredObject(metadata=metadata, data=data)
        except StorageException:
            raise
        except Exception as exc:
            logger.exception(
                "S3StorageAdapter._do_get failed | key=%s | %s: %s", key, type(exc).__name__, exc
            )
            raise self._translate_error("get_object", exc, key=key) from exc

    @log_errors
    async def _do_head(self, *, key: str) -> StorageMetadata | None:
        try:
            async with self._client_context() as client:
                try:
                    response = await client.head_object(Bucket=self.bucket, Key=key)
                except ClientError as client_exc:
                    error_code = client_exc.response.get("Error", {}).get("Code", "")
                    if error_code in {"NoSuchKey", "404", "NotFound"}:
                        return None
                    raise self._translate_error("head_object", client_exc, key=key) from client_exc
                except Exception as head_exc:
                    raise self._translate_error("head_object", head_exc, key=key) from head_exc

            meta_dict = response.get("Metadata", {})
            content_type = response.get("ContentType", "application/json")
            last_modified = response.get("LastModified", datetime.now(UTC))
            content_length = response.get("ContentLength", 0)
            content_hash = meta_dict.get("content-hash") or "0" * 64
            storage_ref = build_storage_uri(self.bucket, key)

            return StorageMetadata(
                key=key,
                bucket=self.bucket,
                size_bytes=content_length,
                content_hash=content_hash,
                content_type=content_type,
                created_at=last_modified,
                storage_ref=storage_ref,
                custom_metadata={k: v for k, v in meta_dict.items() if k != "content-hash"},
            )
        except StorageException:
            raise
        except Exception as exc:
            logger.exception(
                "S3StorageAdapter._do_head failed | key=%s | %s: %s", key, type(exc).__name__, exc
            )
            raise self._translate_error("head_object", exc, key=key) from exc

    @log_errors
    async def _do_delete(self, *, key: str) -> bool:
        try:
            async with self._client_context() as client:
                try:
                    await client.delete_object(Bucket=self.bucket, Key=key)
                    return True
                except Exception as del_exc:
                    raise self._translate_error("delete_object", del_exc, key=key) from del_exc
        except StorageException:
            raise
        except Exception as exc:
            logger.exception(
                "S3StorageAdapter._do_delete failed | key=%s | %s: %s", key, type(exc).__name__, exc
            )
            raise self._translate_error("delete_object", exc, key=key) from exc

    @log_errors
    async def check_health(self) -> bool:
        try:
            async with self._client_context() as client:
                await client.head_bucket(Bucket=self.bucket)
                return True
        except Exception as exc:
            logger.warning(
                "S3StorageAdapter health check failed | bucket=%s | %s: %s",
                self.bucket,
                type(exc).__name__,
                exc,
            )
            return False

    @log_errors
    async def close(self) -> None:
        try:
            # aioboto3 session does not require explicit close, but we provide hook
            pass
        except Exception as exc:
            logger.exception("S3StorageAdapter.close failed | %s: %s", type(exc).__name__, exc)
            raise


__all__ = ["S3StorageAdapter"]
