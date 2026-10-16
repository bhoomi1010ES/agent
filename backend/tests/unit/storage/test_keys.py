"""Unit tests for storage key generation, path-traversal prevention, and metadata validation."""

import uuid

import pytest

from modernization_platform.storage.exceptions import InvalidStorageKeyException
from modernization_platform.storage.keys import (
    build_artifact_storage_key,
    build_storage_uri,
    parse_storage_uri,
    validate_storage_key,
    validate_storage_metadata,
)


def test_validate_storage_key_valid_paths() -> None:
    """Safe POSIX keys pass validation."""
    valid_keys = [
        "artifacts/tenant-1/job-2/manifest.json",
        "data/report_v1.json",
        "file-123.bin",
        "nested/sub/path/item_abc-def.txt",
    ]
    for key in valid_keys:
        assert validate_storage_key(key) == key


def test_validate_storage_key_rejects_empty_or_too_long() -> None:
    """Empty keys and keys exceeding 1024 characters are rejected."""
    with pytest.raises(InvalidStorageKeyException):
        validate_storage_key("")

    with pytest.raises(InvalidStorageKeyException):
        validate_storage_key("a" * 1025)


def test_validate_storage_key_rejects_path_traversal() -> None:
    """Directory traversal sequences are strictly rejected."""
    traversal_keys = [
        "../secret.json",
        "artifacts/../secret.json",
        "artifacts/../../etc/passwd",
        "./manifest.json",
        "artifacts/./manifest.json",
        "artifacts//double_slash.json",
    ]
    for key in traversal_keys:
        with pytest.raises(InvalidStorageKeyException) as exc_info:
            validate_storage_key(key)
        assert "illegal path traversal" in str(exc_info.value) or "invalid" in str(exc_info.value)


def test_validate_storage_key_rejects_slashes_and_drives() -> None:
    """Leading/trailing slashes, backslashes, and Windows drive letters are rejected."""
    invalid_keys = [
        "/leading_slash.json",
        "trailing_slash/",
        "path\\with\\backslashes.json",
        "C:/Windows/System32.dll",
        "D:\\data.txt",
    ]
    for key in invalid_keys:
        with pytest.raises(InvalidStorageKeyException):
            validate_storage_key(key)


def test_validate_storage_key_rejects_control_characters() -> None:
    """Null bytes, newlines, and control characters are rejected."""
    invalid_keys = [
        "file\x00name.json",
        "file\nname.json",
        "file\r\nname.json",
        "file\x1fname.json",
    ]
    for key in invalid_keys:
        with pytest.raises(InvalidStorageKeyException):
            validate_storage_key(key)


def test_validate_storage_metadata_valid() -> None:
    """Valid ASCII alphanumeric metadata keys and values pass."""
    meta = {"content-type": "application/json", "schema-version": "1.0.0", "custom_id": "item-42"}
    cleaned = validate_storage_metadata(meta)
    assert cleaned["content-type"] == "application/json"
    assert cleaned["schema-version"] == "1.0.0"


def test_validate_storage_metadata_rejects_unsafe_keys() -> None:
    """Special characters and spaces in metadata keys are rejected."""
    with pytest.raises(InvalidStorageKeyException):
        validate_storage_metadata({"invalid key!": "value"})

    with pytest.raises(InvalidStorageKeyException):
        validate_storage_metadata({"key$": "value"})


def test_validate_storage_metadata_rejects_control_characters() -> None:
    """Newlines or control characters in metadata values are rejected."""
    with pytest.raises(InvalidStorageKeyException):
        validate_storage_metadata({"key": "value\nwith\nnewlines"})

    with pytest.raises(InvalidStorageKeyException):
        validate_storage_metadata({"key": "value\x00null"})


def test_validate_storage_metadata_rejects_oversized_metadata() -> None:
    """Metadata exceeding 2048 bytes total size is rejected."""
    oversized = {f"key_{i}": "x" * 100 for i in range(25)}
    with pytest.raises(InvalidStorageKeyException):
        validate_storage_metadata(oversized)


def test_build_artifact_storage_key() -> None:
    """Generates an opaque, deterministic, tenant-isolated storage key."""
    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    content_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    key_with_version = build_artifact_storage_key(
        tenant_id=tenant_id,
        job_id=job_id,
        artifact_type="FeasibilityReport",
        content_hash=content_hash,
        version=2,
    )
    assert key_with_version.startswith(f"artifacts/{tenant_id}/{job_id}/feasibilityreport/v2_")
    assert key_with_version.endswith(".json")

    key_no_version = build_artifact_storage_key(
        tenant_id=tenant_id,
        job_id=job_id,
        artifact_type="RepoInventory",
        content_hash=content_hash,
    )
    assert key_no_version.startswith(f"artifacts/{tenant_id}/{job_id}/repoinventory/")
    assert key_no_version.endswith(".json")


def test_storage_uri_roundtrip() -> None:
    """Constructs and parses valid s3:// URIs."""
    bucket = "modernization-artifacts"
    key = "artifacts/tenant-1/job-2/item.json"
    uri = build_storage_uri(bucket, key)
    assert uri == "s3://modernization-artifacts/artifacts/tenant-1/job-2/item.json"

    parsed_bucket, parsed_key = parse_storage_uri(uri)
    assert parsed_bucket == bucket
    assert parsed_key == key


def test_parse_storage_uri_rejects_invalid_schemes_and_traversal() -> None:
    """Rejects malformed schemes, embedded credentials, or traversal."""
    with pytest.raises(InvalidStorageKeyException):
        parse_storage_uri("http://bucket/key.json")

    with pytest.raises(InvalidStorageKeyException):
        parse_storage_uri("s3://user:pass@bucket/key.json")

    with pytest.raises(InvalidStorageKeyException):
        parse_storage_uri("s3://bucket/../secret.json")
