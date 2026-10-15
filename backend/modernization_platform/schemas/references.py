"""Side-effect-free code, storage, evidence, and artifact reference contracts."""

import re
import uuid
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.base import (
    ContractModel,
    Identifier,
    SchemaVersion,
    Sha256Digest,
    ShortText,
)
from modernization_platform.schemas.common import ArtifactType

_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


@log_errors
def validate_repository_path(value: str) -> str:
    """Validate a repository-relative POSIX path without dereferencing it."""
    if not value or len(value) > 1_024:
        raise ValueError("path must contain between 1 and 1024 characters")
    if _CONTROL_CHARACTER.search(value):
        raise ValueError("path contains control characters")
    if "\\" in value or value.startswith("/") or _WINDOWS_DRIVE.match(value):
        raise ValueError("path must be repository-relative and use '/' separators")
    raw_parts = value.split("/")
    if value.endswith("/") or any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("path traversal and ambiguous path segments are forbidden")
    return value


@log_errors
def validate_storage_reference(value: str) -> str:
    """Validate object-reference syntax without performing file or network access."""
    if not value or len(value) > 2_048 or _CONTROL_CHARACTER.search(value):
        raise ValueError("storage reference has an invalid length or characters")
    parsed = urlsplit(value)
    if parsed.scheme not in {"s3", "artifact", "evidence"}:
        raise ValueError("storage reference scheme must be s3, artifact, or evidence")
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("storage reference must name a location and contain no credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("storage reference must not contain a query or fragment")
    if "//" in parsed.path or any(part == ".." for part in parsed.path.split("/")):
        raise ValueError("storage reference traversal is forbidden")
    return value


class EvidenceType(StrEnum):
    """Bounded categories of evidence referenced by artifact conclusions."""

    CODE = "code"
    TEST = "test"
    RUNTIME_CAPTURE = "runtime_capture"
    DATABASE_SCHEMA = "database_schema"
    BUILD_OUTPUT = "build_output"
    DOCUMENTATION = "documentation"
    TOOL_RESULT = "tool_result"


class CodeReference(ContractModel):
    """A syntactic reference to code; end lines are inclusive."""

    repository_id: Identifier
    relative_path: str
    symbol: ShortText | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    content_hash: Sha256Digest | None = None
    revision: Identifier | None = None

    @field_validator("relative_path")
    @classmethod
    @log_errors
    def validate_path(cls, value: str) -> str:
        return validate_repository_path(value)

    @model_validator(mode="after")
    @log_errors
    def validate_line_range(self) -> "CodeReference":
        if self.end_line is not None and self.start_line is None:
            raise ValueError("start_line is required when end_line is present")
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.end_line < self.start_line
        ):
            raise ValueError("end_line is inclusive and must be >= start_line")
        return self


class EvidenceReference(ContractModel):
    """A content-addressed evidence pointer; validation does not fetch its target."""

    evidence_id: uuid.UUID
    evidence_type: EvidenceType
    storage_ref: str
    content_hash: Sha256Digest
    related_artifact_id: uuid.UUID | None = None
    related_execution_id: uuid.UUID | None = None
    provenance: ShortText

    @field_validator("storage_ref")
    @classmethod
    @log_errors
    def validate_storage_ref(cls, value: str) -> str:
        return validate_storage_reference(value)


class ArtifactReference(ContractModel):
    """Stable reference to a specific stored artifact interpretation."""

    artifact_id: uuid.UUID
    artifact_type: ArtifactType
    schema_version: SchemaVersion
    content_hash: Sha256Digest | None = None
