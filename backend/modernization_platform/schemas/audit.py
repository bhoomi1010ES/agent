"""Audit event transport contracts for read and list operations."""

import uuid
from typing import Any

from pydantic import AwareDatetime, Field

from modernization_platform.schemas.base import TransportResponse
from modernization_platform.schemas.jobs import PaginationMetadata


class AuditEventResponse(TransportResponse):
    """Safe, sanitized representation of an immutable audit event."""

    event_id: uuid.UUID
    job_id: uuid.UUID | None = None
    actor: str
    actor_user_id: uuid.UUID | None = None
    action: str
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    event_time: AwareDatetime
    event_version: int = 1


class AuditEventListResponse(TransportResponse):
    """Chronologically ordered audit trail for a modernization job."""

    items: list[AuditEventResponse]
    pagination: PaginationMetadata


__all__ = [
    "AuditEventListResponse",
    "AuditEventResponse",
]
