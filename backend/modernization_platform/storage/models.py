"""Typed models and contracts for object storage metadata and retrieved objects."""

from pydantic import AwareDatetime, Field

from modernization_platform.schemas.base import ContractModel, Sha256Digest


class StorageMetadata(ContractModel):
    """Metadata describing a stored object in S3/MinIO."""

    key: str = Field(min_length=1, max_length=1024)
    bucket: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)
    content_hash: Sha256Digest
    content_type: str = Field(default="application/json", max_length=255)
    created_at: AwareDatetime
    storage_ref: str = Field(min_length=5, max_length=2048)
    custom_metadata: dict[str, str] = Field(default_factory=dict)


class StoredObject(ContractModel):
    """A retrieved storage object containing validated metadata and raw data bytes."""

    metadata: StorageMetadata
    data: bytes


__all__ = ["StorageMetadata", "StoredObject"]
