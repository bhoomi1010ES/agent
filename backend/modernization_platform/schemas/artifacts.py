"""Artifact transport contracts, distinct from persisted payload schemas."""

from typing import Any

from pydantic import Field

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
