"""Typed exceptions for object storage operations."""

from modernization_platform.core.exceptions import ApplicationException


class StorageException(ApplicationException):
    """Base exception for all object storage failures."""

    def __init__(
        self,
        message: str = "An object storage operation failed.",
        code: str = "STORAGE_ERROR",
        status_code: int = 500,
        details: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=status_code, details=details)


class ObjectNotFoundException(StorageException):
    """Raised when an object cannot be found in the target storage bucket."""

    def __init__(
        self,
        message: str = "The requested storage object was not found.",
        key: str | None = None,
    ) -> None:
        details = {"key": key} if key else None
        super().__init__(
            message=message,
            code="OBJECT_NOT_FOUND",
            status_code=404,
            details=details,
        )


class ChecksumMismatchException(StorageException):
    """Raised when an artifact SHA-256 digest fails verification on upload or retrieval."""

    def __init__(
        self,
        message: str = "Calculated SHA-256 digest does not match the expected content hash.",
        expected_hash: str | None = None,
        actual_hash: str | None = None,
    ) -> None:
        details: dict[str, str] = {}
        if expected_hash:
            details["expected_hash"] = expected_hash
        if actual_hash:
            details["actual_hash"] = actual_hash
        super().__init__(
            message=message,
            code="CHECKSUM_MISMATCH",
            status_code=422,
            details=details or None,
        )


class OversizedArtifactException(StorageException):
    """Raised when an artifact payload exceeds the configured maximum byte size."""

    def __init__(
        self,
        message: str = "Artifact payload exceeds maximum allowed size.",
        size_bytes: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        details: dict[str, str] = {}
        if size_bytes is not None:
            details["size_bytes"] = str(size_bytes)
        if max_bytes is not None:
            details["max_bytes"] = str(max_bytes)
        super().__init__(
            message=message,
            code="OVERSIZED_ARTIFACT",
            status_code=413,
            details=details or None,
        )


class EmptyArtifactException(StorageException):
    """Raised when an artifact payload is empty (0 bytes), which is strictly forbidden."""

    def __init__(
        self,
        message: str = "Artifact payload cannot be empty (0 bytes).",
    ) -> None:
        super().__init__(
            message=message,
            code="EMPTY_ARTIFACT",
            status_code=422,
        )


class InvalidStorageKeyException(StorageException):
    """Raised when an object key fails path-traversal, length, or character validation."""

    def __init__(
        self,
        message: str = "Invalid storage object key syntax or illegal path traversal detected.",
        key: str | None = None,
    ) -> None:
        details = {"key": key} if key else None
        super().__init__(
            message=message,
            code="INVALID_STORAGE_KEY",
            status_code=400,
            details=details,
        )


class StorageTimeoutException(StorageException):
    """Raised when an object storage network operation times out."""

    def __init__(
        self,
        message: str = "Object storage operation timed out.",
    ) -> None:
        super().__init__(
            message=message,
            code="STORAGE_TIMEOUT",
            status_code=504,
        )


class StoragePermissionException(StorageException):
    """Raised when storage access is denied by bucket policy or credentials."""

    def __init__(
        self,
        message: str = "Storage access denied by provider permissions.",
    ) -> None:
        super().__init__(
            message=message,
            code="STORAGE_PERMISSION_DENIED",
            status_code=403,
        )


class StorageUnavailableException(StorageException):
    """Raised when the storage provider or service endpoint is unreachable."""

    def __init__(
        self,
        message: str = "Object storage service is currently unreachable.",
    ) -> None:
        super().__init__(
            message=message,
            code="STORAGE_UNAVAILABLE",
            status_code=503,
        )


class StoragePartialUploadException(StorageException):
    """Raised when a multi-part or streaming upload fails partway and requires rollback."""

    def __init__(
        self,
        message: str = "Object storage upload failed partially and was aborted.",
        key: str | None = None,
    ) -> None:
        details = {"key": key} if key else None
        super().__init__(
            message=message,
            code="STORAGE_PARTIAL_UPLOAD",
            status_code=500,
            details=details,
        )


__all__ = [
    "ChecksumMismatchException",
    "EmptyArtifactException",
    "InvalidStorageKeyException",
    "ObjectNotFoundException",
    "OversizedArtifactException",
    "StorageException",
    "StoragePartialUploadException",
    "StoragePermissionException",
    "StorageTimeoutException",
    "StorageUnavailableException",
]
