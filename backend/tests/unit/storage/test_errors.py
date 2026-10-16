"""Unit tests for typed storage exceptions, error hierarchy, and credential safety."""

from modernization_platform.storage.exceptions import (
    ActiveJobArtifactProtectionException,
    ArtifactReferentialIntegrityException,
    ChecksumMismatchException,
    EmptyArtifactException,
    IntegrityVerificationFailedException,
    InvalidStorageKeyException,
    ObjectAlreadyExistsException,
    ObjectNotFoundException,
    OversizedArtifactException,
    StorageAuthenticationException,
    StorageConfigurationException,
    StorageException,
    StorageOperationFailedException,
    StoragePartialUploadException,
    StoragePermissionException,
    StorageTimeoutException,
    StorageUnavailableException,
)


def test_storage_exception_hierarchy() -> None:
    """All custom storage exceptions inherit from base StorageException."""
    exceptions = [
        ObjectNotFoundException("not found"),
        ChecksumMismatchException("hash mismatch"),
        OversizedArtifactException(size_bytes=100, max_bytes=50),
        EmptyArtifactException("empty"),
        InvalidStorageKeyException("bad key"),
        StorageTimeoutException("timeout"),
        StorageUnavailableException("unavailable"),
        StoragePermissionException("denied"),
        StoragePartialUploadException("partial"),
        StorageAuthenticationException("invalid credentials"),
        ObjectAlreadyExistsException("exists"),
        IntegrityVerificationFailedException("tampered"),
        ActiveJobArtifactProtectionException("job active"),
        ArtifactReferentialIntegrityException("referenced in lineage"),
        StorageConfigurationException("bad config"),
        StorageOperationFailedException("operation failed"),
    ]

    for exc in exceptions:
        assert isinstance(exc, StorageException)


def test_credential_sanitization_in_exception_messages() -> None:
    """Storage exceptions must never contain raw AWS secret keys or bearer tokens in their messages."""
    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    token = "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy.sig"

    exc = StorageAuthenticationException(
        "Storage auth failed for endpoint https://s3.amazonaws.com"
    )
    assert secret not in str(exc)
    assert token not in str(exc)


def test_typed_exception_properties() -> None:
    """Specific exceptions retain their structured attributes for error handling."""
    oversized = OversizedArtifactException(size_bytes=2048, max_bytes=1024)
    assert oversized.size_bytes == 2048
    assert oversized.max_bytes == 1024

    key_err = InvalidStorageKeyException("path traversal", key="../evil")
    assert key_err.key == "../evil"

    not_found = ObjectNotFoundException("missing", key="artifacts/item.bin")
    assert not_found.key == "artifacts/item.bin"
