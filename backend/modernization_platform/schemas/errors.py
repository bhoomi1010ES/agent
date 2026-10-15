"""Typed, client-safe error response contracts."""

from typing import Any

from pydantic import Field

from modernization_platform.schemas.base import Identifier, ShortText, TransportResponse


class ValidationIssue(TransportResponse):
    """A validation issue that deliberately excludes the rejected input value."""

    field: str = Field(min_length=1, max_length=500)
    issue: ShortText
    type: Identifier


class ErrorResponse(TransportResponse):
    """Existing platform error envelope represented as a Pydantic contract."""

    code: Identifier
    message: ShortText
    request_id: str = Field(min_length=0, max_length=64)
    details: list[ValidationIssue] | dict[str, Any] | None = None
