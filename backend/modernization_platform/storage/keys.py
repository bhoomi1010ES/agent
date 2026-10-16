"""Safe key construction, path-traversal prevention, and storage URI utilities."""

import logging
import re
import uuid
from urllib.parse import urlsplit

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.references import validate_storage_reference
from modernization_platform.storage.exceptions import InvalidStorageKeyException

logger = logging.getLogger(__name__)

_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
_SAFE_KEY_SEGMENT_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
_SAFE_METADATA_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")

MAX_KEY_LENGTH = 1_024
MAX_METADATA_BYTES = 2_048


@log_errors
def validate_storage_key(key: str) -> str:
    """Validate that an S3/MinIO object key is safe and contains no path traversal.

    Rejects:
    - Empty keys or keys longer than 1024 characters.
    - Keys containing control characters or Windows drive letters.
    - Keys containing backslashes or leading/trailing slashes.
    - Path traversal segments ('.', '..', or consecutive '//').
    - Disallowed special characters.
    """
    try:
        if not key or len(key) > MAX_KEY_LENGTH:
            raise InvalidStorageKeyException(
                f"Storage key length must be between 1 and {MAX_KEY_LENGTH} characters.",
                key=key,
            )
        if _CONTROL_CHAR_PATTERN.search(key):
            raise InvalidStorageKeyException(
                "Storage key contains forbidden control characters.", key=key
            )
        if (
            "\\" in key
            or key.startswith("/")
            or key.endswith("/")
            or _WINDOWS_DRIVE_PATTERN.match(key)
        ):
            raise InvalidStorageKeyException(
                "Storage key must be POSIX-relative without leading/trailing slashes or backslashes.",
                key=key,
            )

        parts = key.split("/")
        for part in parts:
            if part in {"", ".", ".."}:
                raise InvalidStorageKeyException(
                    "Storage key contains illegal path traversal or empty segments.",
                    key=key,
                )
            if not _SAFE_KEY_SEGMENT_PATTERN.match(part):
                raise InvalidStorageKeyException(
                    f"Storage key segment '{part}' contains invalid characters.",
                    key=key,
                )

        return key
    except InvalidStorageKeyException:
        raise
    except Exception as exc:
        logger.exception("validate_storage_key failed | %s: %s", type(exc).__name__, exc)
        raise InvalidStorageKeyException(f"Failed to validate storage key: {exc}", key=key) from exc


@log_errors
def validate_storage_metadata(metadata: dict[str, str] | None) -> dict[str, str]:
    """Validate user metadata keys and values for S3 compatibility and security."""
    try:
        if not metadata:
            return {}

        total_bytes = 0
        cleaned: dict[str, str] = {}
        for k, v in metadata.items():
            if not _SAFE_METADATA_KEY_PATTERN.match(k):
                raise InvalidStorageKeyException(
                    f"Metadata key '{k}' contains invalid characters. Must be alphanumeric, hyphen, or underscore."
                )
            if _CONTROL_CHAR_PATTERN.search(v) or "\n" in v or "\r" in v:
                raise InvalidStorageKeyException(
                    f"Metadata value for '{k}' contains forbidden newline or control characters."
                )
            total_bytes += len(k.encode("utf-8")) + len(v.encode("utf-8"))
            cleaned[k.lower()] = v

        if total_bytes > MAX_METADATA_BYTES:
            raise InvalidStorageKeyException(
                f"Total metadata size ({total_bytes} bytes) exceeds limit of {MAX_METADATA_BYTES} bytes."
            )

        return cleaned
    except InvalidStorageKeyException:
        raise
    except Exception as exc:
        logger.exception("validate_storage_metadata failed | %s: %s", type(exc).__name__, exc)
        raise InvalidStorageKeyException(f"Metadata validation failed: {exc}") from exc


@log_errors
def build_artifact_storage_key(
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    artifact_type: str,
    content_hash: str,
    version: int | None = None,
) -> str:
    """Build an opaque, tenant-scoped, tamper-proof storage key.

    Format: artifacts/{tenant_id}/{job_id}/{artifact_type}/v{version}_{hash[:16]}.json
    """
    try:
        sanitized_type = re.sub(r"[^a-zA-Z0-9_\-]", "_", artifact_type.lower())
        sanitized_hash = re.sub(r"[^a-f0-9]", "", content_hash.lower())[:32]
        ver_str = f"v{version}_" if version is not None else ""
        raw_key = f"artifacts/{tenant_id}/{job_id}/{sanitized_type}/{ver_str}{sanitized_hash}.json"
        return validate_storage_key(raw_key)
    except Exception as exc:
        logger.exception("build_artifact_storage_key failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def build_storage_uri(bucket: str, key: str) -> str:
    """Construct a canonical s3:// URI from a validated bucket and object key."""
    try:
        validated_key = validate_storage_key(key)
        uri = f"s3://{bucket}/{validated_key}"
        validate_storage_reference(uri)
        return uri
    except Exception as exc:
        logger.exception("build_storage_uri failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def parse_storage_uri(storage_uri: str) -> tuple[str, str]:
    """Parse an s3:// URI into (bucket, object_key) with syntax and security validation."""
    try:
        validate_storage_reference(storage_uri)
        parsed = urlsplit(storage_uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        validated_key = validate_storage_key(key)
        return bucket, validated_key
    except InvalidStorageKeyException:
        raise
    except Exception as exc:
        logger.exception("parse_storage_uri failed | %s: %s", type(exc).__name__, exc)
        raise InvalidStorageKeyException(f"Invalid storage URI: {exc}") from exc


__all__ = [
    "MAX_KEY_LENGTH",
    "MAX_METADATA_BYTES",
    "build_artifact_storage_key",
    "build_storage_uri",
    "parse_storage_uri",
    "validate_storage_key",
    "validate_storage_metadata",
]
