"""Artifact identity, lineage, integrity, and producer provenance contracts."""

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AwareDatetime, Field, field_validator, model_validator

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.base import (
    ContractModel,
    Identifier,
    SchemaVersion,
    Sha256Digest,
)
from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.references import validate_storage_reference

_SECRET_LIKE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._-]+|api[_-]?key\s*[=:]|token\s*[=:]|sk-[a-z0-9_-]{12,})"
)


class ProducerKind(StrEnum):
    """Origin class for an artifact producer."""

    AGENT = "agent"
    MANUAL = "manual"
    IMPORT = "import"
    SYSTEM = "system"


class ValidationStatus(StrEnum):
    """Trust-boundary validation state stored with valid artifacts."""

    VALIDATED = "validated"


class ProducerIdentity(ContractModel):
    """System-recorded producer identity; this is not accepted as authorization."""

    kind: ProducerKind
    identifier: Identifier


class ModelPromptProvenance(ContractModel):
    """Model and prompt provenance, separate from artifact schema versioning."""

    provider: Identifier
    model_identifier: Identifier
    model_version: Identifier | None = None
    prompt_template_id: Identifier
    prompt_template_version: SchemaVersion
    generation_config_version: SchemaVersion | None = None

    @field_validator(
        "provider",
        "model_identifier",
        "model_version",
        "prompt_template_id",
        mode="after",
    )
    @classmethod
    @log_errors
    def reject_secret_material(cls, value: str | None) -> str | None:
        if value is not None and _SECRET_LIKE.search(value):
            raise ValueError("provenance fields must not contain credentials or tokens")
        return value


class ArtifactMetadata(ContractModel):
    """Complete metadata envelope for an immutable artifact row."""

    artifact_id: uuid.UUID
    artifact_type: ArtifactType
    schema_version: SchemaVersion
    business_version: int = Field(ge=1)
    content_hash: Sha256Digest
    storage_ref: str
    producer: ProducerIdentity
    parent_artifact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    created_at: AwareDatetime
    job_id: uuid.UUID
    producer_execution_id: uuid.UUID | None = None
    model_prompt: ModelPromptProvenance | None = None
    content_format: str = Field(default="application/json", pattern=r"^application/json$")
    validation_status: ValidationStatus = ValidationStatus.VALIDATED

    @field_validator("storage_ref")
    @classmethod
    @log_errors
    def validate_storage_ref(cls, value: str) -> str:
        return validate_storage_reference(value)

    @field_validator("created_at")
    @classmethod
    @log_errors
    def normalize_created_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    @log_errors
    def validate_lineage(self) -> "ArtifactMetadata":
        if len(self.parent_artifact_ids) != len(set(self.parent_artifact_ids)):
            raise ValueError("parent_artifact_ids must be unique")
        if self.artifact_id in self.parent_artifact_ids:
            raise ValueError("an artifact cannot derive from itself")
        if self.producer.kind is ProducerKind.AGENT and self.producer_execution_id is None:
            raise ValueError("agent-produced artifacts require producer_execution_id")
        if self.producer.kind is not ProducerKind.AGENT and self.model_prompt is not None:
            raise ValueError("model_prompt provenance is only valid for agent-produced artifacts")
        return self
