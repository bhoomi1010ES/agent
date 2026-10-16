"""Typed exceptions for object storage operations."""

import uuid

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
        self.key = key
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
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
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
        self.key = key
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


class StorageAuthenticationException(StorageException):
    """Raised when storage provider authentication fails (invalid credentials)."""

    def __init__(
        self,
        message: str = "Object storage authentication failed. Invalid credentials.",
    ) -> None:
        super().__init__(
            message=message,
            code="STORAGE_AUTHENTICATION_ERROR",
            status_code=401,
        )


class ObjectAlreadyExistsException(StorageException):
    """Raised when attempting to create an object that already exists under immutable policy."""

    def __init__(
        self,
        message: str = "Storage object already exists and is immutable.",
        key: str | None = None,
    ) -> None:
        details = {"key": key} if key else None
        super().__init__(
            message=message,
            code="OBJECT_ALREADY_EXISTS",
            status_code=409,
            details=details,
        )


class IntegrityVerificationFailedException(StorageException):
    """Raised when an artifact fails cryptographic integrity verification."""

    def __init__(
        self,
        message: str = "Cryptographic integrity verification failed for stored artifact.",
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
            code="INTEGRITY_VERIFICATION_FAILED",
            status_code=422,
            details=details or None,
        )


class ActiveJobArtifactProtectionException(StorageException):
    """Raised when deletion of an artifact is blocked because its job is active."""

    def __init__(
        self,
        message: str = "Artifact cannot be deleted because its parent job is active.",
        job_id: str | uuid.UUID | None = None,
        job_status: str | None = None,
        artifact_id: str | uuid.UUID | None = None,
    ) -> None:
        self.job_id = str(job_id) if job_id is not None else None
        self.job_status = job_status
        self.artifact_id = str(artifact_id) if artifact_id is not None else None
        details: dict[str, str] = {}
        if self.job_id:
            details["job_id"] = self.job_id
        if self.job_status:
            details["job_status"] = self.job_status
        if self.artifact_id:
            details["artifact_id"] = self.artifact_id
        super().__init__(
            message=message,
            code="ACTIVE_JOB_ARTIFACT_PROTECTION",
            status_code=409,
            details=details or None,
        )


class ArtifactReferentialIntegrityException(StorageException):
    """Raised when deletion is blocked because other artifacts depend on this artifact."""

    def __init__(
        self,
        message: str = "Artifact cannot be deleted because downstream artifacts depend on it.",
        artifact_id: str | uuid.UUID | None = None,
        dependent_ids: list[str] | list[uuid.UUID] | None = None,
    ) -> None:
        self.artifact_id = str(artifact_id) if artifact_id is not None else None
        self.dependent_ids = [str(d) for d in dependent_ids] if dependent_ids else []
        details: dict[str, str] = {}
        if self.artifact_id:
            details["artifact_id"] = self.artifact_id
        if self.dependent_ids:
            details["dependent_count"] = str(len(self.dependent_ids))
        super().__init__(
            message=message,
            code="ARTIFACT_REFERENTIAL_INTEGRITY_VIOLATION",
            status_code=409,
            details=details or None,
        )


class StorageConfigurationException(StorageException):
    """Raised when storage configuration is invalid or missing required parameters."""

    def __init__(
        self,
        message: str = "Object storage configuration error.",
    ) -> None:
        super().__init__(
            message=message,
            code="STORAGE_CONFIGURATION_ERROR",
            status_code=500,
        )


class StorageOperationFailedException(StorageException):
    """Raised when an unrecoverable object storage operation fails."""

    def __init__(
        self,
        message: str = "Object storage operation failed.",
        operation: str | None = None,
    ) -> None:
        details = {"operation": operation} if operation else None
        super().__init__(
            message=message,
            code="STORAGE_OPERATION_FAILED",
            status_code=500,
            details=details,
        )


__all__ = [
    "ActiveJobArtifactProtectionException",
    "ArtifactReferentialIntegrityException",
    "ChecksumMismatchException",
    "EmptyArtifactException",
    "IntegrityVerificationFailedException",
    "InvalidStorageKeyException",
    "ObjectAlreadyExistsException",
    "ObjectNotFoundException",
    "OversizedArtifactException",
    "StorageAuthenticationException",
    "StorageConfigurationException",
    "StorageException",
    "StorageOperationFailedException",
    "StoragePartialUploadException",
    "StoragePermissionException",
    "StorageTimeoutException",
    "StorageUnavailableException",
]
