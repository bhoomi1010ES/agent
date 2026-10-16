"""Artifact transport contracts, distinct from persisted payload schemas."""

import uuid
from typing import Any

from pydantic import AwareDatetime, Field

from modernization_platform.schemas.base import SchemaVersion, TransportRequest, TransportResponse
from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.metadata import ArtifactMetadata


class ArtifactValidationRequest(TransportRequest):
    """Untrusted artifact payload paired with workflow-selected expectations."""

    expected_artifact_type: ArtifactType
    expected_schema_version: SchemaVersion
    payload: dict[str, Any] = Field(max_length=10_000)


class ArtifactResponse(TransportResponse):
    """Validated artifact metadata returned without exposing an ORM object."""

    metadata: ArtifactMetadata


class ArtifactDetailResponse(TransportResponse):
    """Full metadata and references for an artifact record."""

    artifact_id: uuid.UUID
    job_id: uuid.UUID
    artifact_type: str
    version: int
    content_hash: str
    storage_ref: str
    derived_from: list[str] = Field(default_factory=list)
    artifact_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime
    status: str = "available"
    size_bytes: int | None = None
    content_type: str | None = "application/json"


class ArtifactListResponse(TransportResponse):
    """Collection of artifacts belonging to a modernization job."""

    items: list[ArtifactDetailResponse]
    total: int


class ArtifactLineageResponse(TransportResponse):
    """Direct parent and child lineage graph for an artifact."""

    artifact_id: uuid.UUID
    job_id: uuid.UUID
    parents: list[ArtifactDetailResponse] = Field(default_factory=list)
    children: list[ArtifactDetailResponse] = Field(default_factory=list)


class ArtifactIntegrityVerificationResponse(TransportResponse):
    """Outcome of cryptographic and storage integrity verification."""

    artifact_id: uuid.UUID
    job_id: uuid.UUID
    verified: bool
    content_hash: str
    size_bytes: int | None = None
    verified_at: AwareDatetime


class ArtifactDeleteResponse(TransportResponse):
    """Result of safe retention deletion."""

    artifact_id: uuid.UUID
    job_id: uuid.UUID
    deleted: bool
    message: str


__all__ = [
    "ArtifactDeleteResponse",
    "ArtifactDetailResponse",
    "ArtifactIntegrityVerificationResponse",
    "ArtifactLineageResponse",
    "ArtifactListResponse",
    "ArtifactResponse",
    "ArtifactValidationRequest",
]
