"""Typed authentication and authorization API responses."""

import uuid

from modernization_platform.schemas.base import TransportResponse
from modernization_platform.schemas.status import JobStatus


class SecuredJobResponse(TransportResponse):
    """Authorized job summary scoped to the authenticated principal."""

    job_id: uuid.UUID
    tenant_id: uuid.UUID
    owner_user_id: uuid.UUID
    status: JobStatus


class SecuredArtifactResponse(TransportResponse):
    """Authorized artifact summary without an object-storage credential or raw payload."""

    artifact_id: uuid.UUID
    job_id: uuid.UUID
    artifact_type: str
    version: int
    content_hash: str


__all__ = ["SecuredArtifactResponse", "SecuredJobResponse"]
