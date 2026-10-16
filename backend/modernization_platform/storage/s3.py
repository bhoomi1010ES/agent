"""S3-compatible asynchronous storage adapter for AWS S3 and MinIO."""

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import AsyncIterator
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
    ChecksumMismatchException,
    EmptyArtifactException,
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
        multipart_threshold: int = 8_388_608,
        multipart_chunk_size: int = 5_242_880,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(bucket=bucket, max_artifact_size_bytes=max_artifact_size_bytes)
        self.endpoint_url = endpoint_url
        self.region_name = region_name
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.use_ssl = use_ssl
        self.multipart_threshold = multipart_threshold
        self.multipart_chunk_size = multipart_chunk_size
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
        try:
            hasher = hashlib.sha256()
            first_chunks: list[bytes] = []
            buffered_size = 0
            is_stream_finished = False

            async for chunk in content_stream:
                if not chunk:
                    continue
                buffered_size += len(chunk)
                if buffered_size > self.max_artifact_size_bytes:
                    raise OversizedArtifactException(
                        f"Artifact payload exceeded maximum size of {self.max_artifact_size_bytes} bytes during streaming.",
                        size_bytes=buffered_size,
                        max_bytes=self.max_artifact_size_bytes,
                    )
                hasher.update(chunk)
                first_chunks.append(chunk)
                if buffered_size >= self.multipart_threshold:
                    break
            else:
                is_stream_finished = True

            # If stream finished under threshold, use single put_object
            if is_stream_finished:
                data = b"".join(first_chunks)
                if len(data) == 0:
                    raise EmptyArtifactException("Artifact payload cannot be empty (0 bytes).")
                actual_hash = hasher.hexdigest()
                if expected_hash is not None and expected_hash.lower() != actual_hash.lower():
                    raise ChecksumMismatchException(
                        f"Claimed content hash ({expected_hash}) does not match payload digest ({actual_hash}).",
                        expected_hash=expected_hash,
                        actual_hash=actual_hash,
                    )
                return await self._do_put(
                    key=key,
                    data=data,
                    content_type=content_type,
                    content_hash=actual_hash,
                    metadata=metadata,
                )

            # Initiate S3 multipart upload
            custom_meta = {**metadata}
            async with self._client_context() as client:
                mp_resp = await client.create_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    ContentType=content_type,
                    Metadata=custom_meta,
                )
                upload_id = mp_resp["UploadId"]
                parts: list[dict[str, Any]] = []
                part_number = 1
                current_buffer = bytearray(b"".join(first_chunks))
                total_bytes = len(current_buffer)

                try:
                    while len(current_buffer) >= self.multipart_chunk_size:
                        part_data = bytes(current_buffer[: self.multipart_chunk_size])
                        del current_buffer[: self.multipart_chunk_size]
                        part_resp = await client.upload_part(
                            Bucket=self.bucket,
                            Key=key,
                            UploadId=upload_id,
                            PartNumber=part_number,
                            Body=part_data,
                        )
                        parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})
                        part_number += 1

                    async for chunk in content_stream:
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > self.max_artifact_size_bytes:
                            raise OversizedArtifactException(
                                f"Artifact payload exceeded maximum size of {self.max_artifact_size_bytes} bytes during streaming.",
                                size_bytes=total_bytes,
                                max_bytes=self.max_artifact_size_bytes,
                            )
                        hasher.update(chunk)
                        current_buffer.extend(chunk)

                        while len(current_buffer) >= self.multipart_chunk_size:
                            part_data = bytes(current_buffer[: self.multipart_chunk_size])
                            del current_buffer[: self.multipart_chunk_size]
                            part_resp = await client.upload_part(
                                Bucket=self.bucket,
                                Key=key,
                                UploadId=upload_id,
                                PartNumber=part_number,
                                Body=part_data,
                            )
                            parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})
                            part_number += 1

                    if len(current_buffer) > 0:
                        part_resp = await client.upload_part(
                            Bucket=self.bucket,
                            Key=key,
                            UploadId=upload_id,
                            PartNumber=part_number,
                            Body=bytes(current_buffer),
                        )
                        parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})

                    actual_hash = hasher.hexdigest()
                    if expected_hash is not None and expected_hash.lower() != actual_hash.lower():
                        raise ChecksumMismatchException(
                            f"Claimed content hash ({expected_hash}) does not match payload digest ({actual_hash}).",
                            expected_hash=expected_hash,
                            actual_hash=actual_hash,
                        )

                    await client.complete_multipart_upload(
                        Bucket=self.bucket,
                        Key=key,
                        UploadId=upload_id,
                        MultipartUpload={"Parts": parts},
                    )

                    now = datetime.now(UTC)
                    storage_ref = build_storage_uri(self.bucket, key)
                    return StorageMetadata(
                        key=key,
                        bucket=self.bucket,
                        size_bytes=total_bytes,
                        content_hash=actual_hash,
                        content_type=content_type,
                        created_at=now,
                        storage_ref=storage_ref,
                        custom_metadata=metadata,
                    )
                except Exception as upload_exc:
                    with contextlib.suppress(Exception):
                        await client.abort_multipart_upload(
                            Bucket=self.bucket,
                            Key=key,
                            UploadId=upload_id,
                        )
                    raise self._translate_error(
                        "stream_upload", upload_exc, key=key
                    ) from upload_exc
        except StorageException:
            raise
        except Exception as exc:
            logger.exception("S3StorageAdapter._do_stream_upload failed | key=%s: %s", key, exc)
            raise self._translate_error("stream_upload", exc, key=key) from exc

    @log_errors
    async def _do_stream_download(
        self,
        *,
        key: str,
        chunk_size: int,
        expected_hash: str | None,
    ) -> tuple[StorageMetadata, AsyncIterator[bytes]]:
        try:
            client_ctx = self._client_context()
            client = await client_ctx.__aenter__()
            try:
                response = await client.get_object(Bucket=self.bucket, Key=key)
            except Exception as get_exc:
                await client_ctx.__aexit__(None, None, None)
                raise self._translate_error("stream_download", get_exc, key=key) from get_exc

            meta_dict = response.get("Metadata", {})
            content_type = response.get("ContentType", "application/octet-stream")
            last_modified = response.get("LastModified", datetime.now(UTC))
            content_length = response.get("ContentLength", 0)
            content_hash = meta_dict.get("content-hash") or (expected_hash or "0" * 64)
            storage_ref = build_storage_uri(self.bucket, key)

            metadata = StorageMetadata(
                key=key,
                bucket=self.bucket,
                size_bytes=content_length,
                content_hash=content_hash,
                content_type=content_type,
                created_at=last_modified,
                storage_ref=storage_ref,
                custom_metadata={k: v for k, v in meta_dict.items() if k != "content-hash"},
            )

            async def _body_stream() -> AsyncIterator[bytes]:
                hasher = hashlib.sha256()
                try:
                    async with response["Body"] as stream:
                        while True:
                            chunk = await stream.read(chunk_size)
                            if not chunk:
                                break
                            hasher.update(chunk)
                            yield chunk

                    actual_hash = hasher.hexdigest()
                    if expected_hash is not None and expected_hash.lower() != actual_hash.lower():
                        raise ChecksumMismatchException(
                            f"Retrieved content digest ({actual_hash}) does not match expected hash ({expected_hash}).",
                            expected_hash=expected_hash,
                            actual_hash=actual_hash,
                        )
                finally:
                    await client_ctx.__aexit__(None, None, None)

            return metadata, _body_stream()
        except StorageException:
            raise
        except Exception as exc:
            logger.exception("S3StorageAdapter._do_stream_download failed | key=%s: %s", key, exc)
            raise self._translate_error("stream_download", exc, key=key) from exc

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
