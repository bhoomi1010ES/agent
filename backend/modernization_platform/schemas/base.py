"""Shared Pydantic v2 conventions for public platform contracts."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Identifier = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128),
]
ShortText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500),
]
LongText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=10_000),
]
SchemaVersion = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$",
    ),
]
Sha256Digest = Annotated[
    str,
    StringConstraints(strict=True, to_lower=True, pattern=r"^[0-9a-f]{64}$"),
]


class ContractModel(BaseModel):
    """Base for finalized contracts at trusted workflow boundaries.

    Unknown fields are rejected and instances are immutable. JSON serialization uses
    Pydantic's JSON-mode representations; canonical hashing is defined separately.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
        use_enum_values=False,
    )


class TransportRequest(ContractModel):
    """Base for API inputs; identity and authorization remain server responsibilities."""


class TransportResponse(ContractModel):
    """Base for API outputs that must not expose ORM instances directly."""
