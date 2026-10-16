"""Production-grade S3-compatible object storage package."""

from modernization_platform.storage.base import StorageAdapter
from modernization_platform.storage.exceptions import (
    ChecksumMismatchException,
    EmptyArtifactException,
    InvalidStorageKeyException,
    ObjectNotFoundException,
    OversizedArtifactException,
    StorageException,
    StoragePartialUploadException,
    StoragePermissionException,
    StorageTimeoutException,
    StorageUnavailableException,
)
from modernization_platform.storage.factory import create_storage_adapter, get_storage_adapter
from modernization_platform.storage.keys import (
    MAX_KEY_LENGTH,
    MAX_METADATA_BYTES,
    build_artifact_storage_key,
    build_storage_uri,
    parse_storage_uri,
    validate_storage_key,
    validate_storage_metadata,
)
from modernization_platform.storage.memory import MemoryStorageAdapter
from modernization_platform.storage.models import StorageMetadata, StoredObject
from modernization_platform.storage.s3 import S3StorageAdapter
from modernization_platform.storage.service import ArtifactStorageService

__all__ = [
    "MAX_KEY_LENGTH",
    "MAX_METADATA_BYTES",
    "ArtifactStorageService",
    "ChecksumMismatchException",
    "EmptyArtifactException",
    "InvalidStorageKeyException",
    "MemoryStorageAdapter",
    "ObjectNotFoundException",
    "OversizedArtifactException",
    "S3StorageAdapter",
    "StorageAdapter",
    "StorageException",
    "StorageMetadata",
    "StoragePartialUploadException",
    "StoragePermissionException",
    "StorageTimeoutException",
    "StorageUnavailableException",
    "StoredObject",
    "build_artifact_storage_key",
    "build_storage_uri",
    "create_storage_adapter",
    "get_storage_adapter",
    "parse_storage_uri",
    "validate_storage_key",
    "validate_storage_metadata",
]
