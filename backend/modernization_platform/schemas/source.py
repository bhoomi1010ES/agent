"""Transport contracts for source ingestion, repository metadata, and provenance."""

import uuid
from typing import Any

from pydantic import AwareDatetime, Field, SecretStr

from modernization_platform.schemas.base import (
    Identifier,
    ShortText,
    TransportRequest,
    TransportResponse,
)


class SourceIngestRequest(TransportRequest):
    """Payload to trigger or override source code ingestion for a job."""

    ref_override: Identifier | None = Field(
        default=None,
        description="Optional branch, tag, or commit override for ingestion",
    )
    git_token: SecretStr | None = Field(
        default=None,
        description="Optional personal access token or bearer token for private repository",
    )
    git_username: ShortText | None = Field(
        default=None,
        description="Optional username for HTTP Basic Auth with private repository",
    )
    git_password: SecretStr | None = Field(
        default=None,
        description="Optional password for HTTP Basic Auth with private repository",
    )


class RepositoryMetadataResponse(TransportResponse):
    """Structural metadata captured from checked-out repository."""

    default_branch: str | None = None
    size_bytes: int = Field(ge=0)
    file_count: int = Field(ge=0)
    commit_author: str | None = None
    commit_author_email: str | None = None
    commit_timestamp: AwareDatetime | None = None
    commit_message: str | None = None
    tree_hash: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class SourceProvenanceResponse(TransportResponse):
    """Immutable, reproducible source code provenance record for a job."""

    job_id: uuid.UUID
    repository_url: str
    provider: str
    requested_ref: str
    resolved_commit_sha: str
    branch: str | None = None
    tree_hash: str | None = None
    commit_author: str | None = None
    commit_author_email: str | None = None
    commit_timestamp: AwareDatetime | None = None
    commit_message: str | None = None
    file_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    provenance_hash: str
    ingestion_status: str
    ingested_at: AwareDatetime
    repository_metadata: dict[str, Any] = Field(default_factory=dict)


class ModuleBranchRequest(TransportRequest):
    """Request to create an isolated module branch for modernization."""

    module: Identifier = Field(description="Target module identifier to isolate")


class ModuleBranchResponse(TransportResponse):
    """Response confirming creation of isolated module branch."""

    job_id: uuid.UUID
    module: str
    branch_name: str
    created_at: AwareDatetime


__all__ = [
    "ModuleBranchRequest",
    "ModuleBranchResponse",
    "RepositoryMetadataResponse",
    "SourceIngestRequest",
    "SourceProvenanceResponse",
]
