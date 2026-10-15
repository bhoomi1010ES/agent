"""Validation-before-persistence service for immutable typed artifacts."""

import logging
import uuid
from typing import Any

from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.core.exceptions import NotFoundException
from modernization_platform.repositories.agent_runs import AgentRunRepository
from modernization_platform.repositories.artifacts import ArtifactRepository
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.schemas.base import ContractModel
from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.errors import ValidationIssue
from modernization_platform.schemas.metadata import (
    ArtifactMetadata,
    ModelPromptProvenance,
    ProducerIdentity,
    ProducerKind,
    ValidationStatus,
)
from modernization_platform.schemas.references import validate_storage_reference
from modernization_platform.schemas.validation import ArtifactValidationError, parse_artifact
from modernization_platform.security.authorization import require_permission
from modernization_platform.security.permissions import Permission
from modernization_platform.security.principals import (
    AuthenticatedPrincipal,
    WorkerAuthorizationContext,
)
from modernization_platform.services.authorization import AuthorizationService

logger = logging.getLogger(__name__)


class ArtifactPersistenceResult(ContractModel):
    """Typed outcome that distinguishes a stored artifact from a rejected attempt."""

    persisted: bool
    metadata: ArtifactMetadata | None = None
    error_code: str | None = Field(default=None, max_length=100)
    issues: tuple[ValidationIssue, ...] = ()

    @model_validator(mode="after")
    @log_errors
    def validate_result_state(self) -> "ArtifactPersistenceResult":
        if self.persisted and (self.metadata is None or self.error_code is not None):
            raise ValueError("persisted results require metadata and no error")
        if not self.persisted and (self.metadata is not None or self.error_code is None):
            raise ValueError("rejected results require an error and no metadata")
        return self


class ArtifactPersistenceService:
    """Coordinate artifact validation and repositories without committing transactions.

    Authorization is rechecked here even when an API or scheduler already checked it.
    Producer metadata is provenance only and is never treated as authorization.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._artifacts = ArtifactRepository(session)
        self._runs = AgentRunRepository(session)
        self._audit = AuditEventRepository(session)
        self._authorization = AuthorizationService(session)

    @log_errors
    async def persist(
        self,
        *,
        authorization_context: AuthenticatedPrincipal | WorkerAuthorizationContext,
        job_id: uuid.UUID,
        expected_type: ArtifactType,
        expected_schema_version: str,
        payload: dict[str, Any] | str | bytes,
        storage_ref: str,
        producer: ProducerIdentity,
        parent_artifact_ids: list[uuid.UUID] | None = None,
        producer_execution_id: uuid.UUID | None = None,
        model_prompt: ModelPromptProvenance | None = None,
        claimed_content_hash: str | None = None,
        correlation_id: str | None = None,
    ) -> ArtifactPersistenceResult:
        """Validate, hash, validate lineage, and stage one append-only artifact row."""
        parents = parent_artifact_ids or []
        try:
            actor_user_id = await self._authorize(
                authorization_context=authorization_context,
                job_id=job_id,
            )
            self._validate_storage_reference(storage_ref)
            validated = parse_artifact(
                payload,
                expected_type=expected_type,
                expected_schema_version=expected_schema_version,
            )
            self._validate_claimed_hash(claimed_content_hash, validated.content_hash)
            await self._validate_lineage(job_id, parents)
            await self._validate_producer(job_id, producer, producer_execution_id, model_prompt)

            artifact_id = uuid.uuid4()
            artifact_row = await self._artifacts._append_artifact_after_authorization(
                job_id=job_id,
                artifact_type=expected_type.value,
                content_hash=validated.content_hash,
                storage_ref=storage_ref,
                derived_from=[str(parent_id) for parent_id in parents],
                artifact_metadata=self._metadata_payload(
                    expected_schema_version, producer, model_prompt
                ),
                produced_by_run_id=producer_execution_id,
                artifact_id=artifact_id,
            )
            metadata = ArtifactMetadata(
                artifact_id=artifact_row.id,
                artifact_type=expected_type,
                schema_version=expected_schema_version,
                business_version=artifact_row.version,
                content_hash=artifact_row.content_hash,
                storage_ref=artifact_row.storage_ref,
                producer=producer,
                parent_artifact_ids=parents,
                created_at=artifact_row.created_at,
                job_id=job_id,
                producer_execution_id=producer_execution_id,
                model_prompt=model_prompt,
            )
            await self._audit.append_event(
                actor=str(actor_user_id),
                actor_user_id=actor_user_id,
                action="ARTIFACT_VALIDATED_AND_STAGED",
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "artifact_id": str(artifact_row.id),
                    "artifact_type": expected_type.value,
                    "schema_version": expected_schema_version,
                    "content_hash": validated.content_hash,
                },
            )
            return ArtifactPersistenceResult(persisted=True, metadata=metadata)
        except ArtifactValidationError as exc:
            await self._record_rejection(
                job_id=job_id,
                actor_user_id=actor_user_id,
                artifact_type=expected_type,
                schema_version=expected_schema_version,
                error=exc,
                correlation_id=correlation_id,
            )
            return ArtifactPersistenceResult(
                persisted=False,
                error_code=exc.code,
                issues=exc.issues,
            )

    @log_errors
    async def _authorize(
        self,
        *,
        authorization_context: AuthenticatedPrincipal | WorkerAuthorizationContext,
        job_id: uuid.UUID,
    ) -> uuid.UUID:
        """Authorize a human or revalidate a worker before touching artifact state."""
        if isinstance(authorization_context, AuthenticatedPrincipal):
            require_permission(authorization_context, Permission.ARTIFACT_CREATE)
            await self._authorization.get_job(authorization_context, job_id)
            return authorization_context.user_id
        if authorization_context.job_id != job_id:
            raise NotFoundException()
        await self._authorization.authorize_worker(
            authorization_context,
            Permission.ARTIFACT_CREATE,
        )
        return authorization_context.initiator_user_id

    @staticmethod
    @log_errors
    def _validate_storage_reference(storage_ref: str) -> None:
        try:
            validate_storage_reference(storage_ref)
        except ValueError as exc:
            raise ArtifactValidationError(
                "INVALID_STORAGE_REFERENCE", "Storage reference syntax is invalid"
            ) from exc

    @staticmethod
    @log_errors
    def _validate_claimed_hash(claimed_hash: str | None, actual_hash: str) -> None:
        if claimed_hash is not None and claimed_hash.lower() != actual_hash:
            raise ArtifactValidationError(
                "CONTENT_HASH_MISMATCH", "Claimed content hash does not match validated content"
            )

    @log_errors
    async def _validate_lineage(
        self, job_id: uuid.UUID, parent_artifact_ids: list[uuid.UUID]
    ) -> None:
        if len(parent_artifact_ids) != len(set(parent_artifact_ids)):
            raise ArtifactValidationError(
                "INVALID_LINEAGE", "Parent artifact identifiers must be unique"
            )
        parent_rows = await self._artifacts._get_by_ids_unscoped(parent_artifact_ids)
        if len(parent_rows) != len(parent_artifact_ids) or any(
            parent.job_id != job_id for parent in parent_rows
        ):
            raise ArtifactValidationError(
                "INVALID_LINEAGE", "Every parent artifact must exist in the same job"
            )

    @log_errors
    async def _validate_producer(
        self,
        job_id: uuid.UUID,
        producer: ProducerIdentity,
        execution_id: uuid.UUID | None,
        model_prompt: ModelPromptProvenance | None,
    ) -> None:
        if producer.kind is ProducerKind.AGENT:
            if execution_id is None:
                raise ArtifactValidationError(
                    "INVALID_PRODUCER", "Agent artifacts require a producer execution"
                )
            producer_run = await self._runs.get_by_id(execution_id)
            if producer_run is None or producer_run.job_id != job_id:
                raise ArtifactValidationError(
                    "INVALID_PRODUCER", "Producer execution must belong to the same job"
                )
        elif execution_id is not None:
            raise ArtifactValidationError(
                "INVALID_PRODUCER", "Only agent producers may reference an agent execution"
            )
        if producer.kind is not ProducerKind.AGENT and model_prompt is not None:
            raise ArtifactValidationError(
                "INVALID_PROVENANCE", "Model provenance requires an agent producer"
            )

    @staticmethod
    @log_errors
    def _metadata_payload(
        schema_version: str,
        producer: ProducerIdentity,
        model_prompt: ModelPromptProvenance | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": schema_version,
            "producer": producer.model_dump(mode="json"),
            "model_prompt": (
                model_prompt.model_dump(mode="json") if model_prompt is not None else None
            ),
            "content_format": "application/json",
            "validation_status": ValidationStatus.VALIDATED.value,
            "canonicalization": "rfc8259-sort-keys-utf8-v1",
        }

    @log_errors
    async def _record_rejection(
        self,
        *,
        job_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        artifact_type: ArtifactType,
        schema_version: str,
        error: ArtifactValidationError,
        correlation_id: str | None,
    ) -> None:
        """Stage a safe audit event without payload content or sensitive values."""
        await self._audit.append_event(
            actor=str(actor_user_id),
            actor_user_id=actor_user_id,
            action="ARTIFACT_VALIDATION_REJECTED",
            job_id=job_id,
            correlation_id=correlation_id,
            payload={
                "artifact_type": artifact_type.value,
                "schema_version": schema_version,
                "error_code": error.code,
                "fields": [issue.field for issue in error.issues],
            },
        )


__all__ = ["ArtifactPersistenceResult", "ArtifactPersistenceService"]
