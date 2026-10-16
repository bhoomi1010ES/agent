"""Job lifecycle, artifact retrieval, and audit trail REST API endpoints."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.core.exceptions import (
    BadRequestException,
    NotFoundException,
)
from modernization_platform.db.session import get_db_session
from modernization_platform.integrations.git.models import GitCredentials
from modernization_platform.schemas.artifacts import (
    ArtifactDetailResponse,
    ArtifactListResponse,
)
from modernization_platform.schemas.audit import (
    AuditEventListResponse,
    AuditEventResponse,
)
from modernization_platform.schemas.gates import (
    GateDetailResponse,
    GateListResponse,
)
from modernization_platform.schemas.jobs import (
    JobCreateRequest,
    JobCreateResponse,
    JobDetailResponse,
    JobLifecycleActionRequest,
    JobLifecycleActionResponse,
    JobListResponse,
    JobStatusResponse,
    PaginationMetadata,
)
from modernization_platform.schemas.source import (
    ModuleBranchRequest,
    ModuleBranchResponse,
    SourceIngestRequest,
    SourceProvenanceResponse,
)
from modernization_platform.schemas.status import JobStatus
from modernization_platform.security.dependencies import CurrentPrincipal
from modernization_platform.services.authorization import AuthorizationService
from modernization_platform.services.jobs import JobService
from modernization_platform.services.source_ingestion import SourceIngestionService

logger = logging.getLogger(__name__)

router = APIRouter()


@log_errors
def _validate_idempotency_key(key: str | None) -> str | None:
    """Validate format and bounds for incoming idempotency key."""
    if key is None:
        return None
    trimmed = key.strip()
    if not trimmed or len(trimmed) > 128:
        raise BadRequestException(
            message="Idempotency-Key header must be between 1 and 128 characters.",
            code="INVALID_IDEMPOTENCY_KEY",
        )
    return trimmed


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_request: JobCreateRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", description="Unique request idempotency key")
    ] = None,
) -> JobCreateResponse:
    """Create a modernization job, initialize tenant membership, and log an audit event."""
    try:
        correlation_id = request.headers.get("X-Correlation-ID")
        validated_key = _validate_idempotency_key(idempotency_key)
        service = JobService(session)
        job = await service.create_job(
            principal=principal,
            source_repository=str(job_request.source_repository),
            source_revision=str(job_request.source_revision),
            target_stack_spec=job_request.target_stack.model_dump(mode="json"),
            budget=job_request.budget.model_dump(mode="json"),
            correlation_id=correlation_id,
            idempotency_key=validated_key,
        )
        await session.commit()
        logger.info(
            "Modernization job created | job_id=%s tenant_id=%s owner_user_id=%s status=%s version=%d",
            job.id,
            principal.tenant_id,
            principal.user_id,
            job.status,
            job.version,
        )
        return JobCreateResponse(
            job_id=job.id,
            status=JobStatus(job.status),
            created_at=job.created_at or datetime.now(UTC),
            version=job.version,
        )
    except Exception:
        await session.rollback()
        raise


@router.get("", response_model=JobListResponse)
async def list_jobs(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    status: Annotated[JobStatus | None, Query()] = None,
) -> JobListResponse:
    """List modernization jobs visible to the principal within their authorized tenant scope."""
    try:
        service = JobService(session)
        jobs, total = await service.list_jobs(
            principal=principal,
            offset=offset,
            limit=limit,
            status=status.value if status else None,
        )
        items = [
            service.to_summary_response(
                job=job,
                default_tenant_id=principal.tenant_id,
                default_user_id=principal.user_id,
            )
            for job in jobs
        ]
        return JobListResponse(
            items=items,
            pagination=PaginationMetadata(offset=offset, limit=limit, total=total),
        )
    except Exception:
        raise


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JobDetailResponse:
    """Retrieve full job details and lifecycle state only within authorized scope."""
    try:
        service = JobService(session)
        job = await service.get_job(principal=principal, job_id=job_id)
        return service.to_detail_response(job)
    except Exception:
        raise


@router.get("/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JobStatusResponse:
    """Retrieve current job lifecycle status, version, and stage diagnostics."""
    try:
        service = JobService(session)
        return await service.get_job_status(principal=principal, job_id=job_id)
    except Exception:
        raise


@router.post("/{job_id}/pause", response_model=JobLifecycleActionResponse)
async def pause_job(
    job_id: uuid.UUID,
    action_request: JobLifecycleActionRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", description="Unique request idempotency key")
    ] = None,
) -> JobLifecycleActionResponse:
    """Cooperatively pause a running modernization job."""
    try:
        correlation_id = request.headers.get("X-Correlation-ID")
        validated_key = _validate_idempotency_key(idempotency_key)
        service = JobService(session)
        job = await service.pause_job(
            principal=principal,
            job_id=job_id,
            expected_version=action_request.expected_version,
            reason=action_request.reason,
            correlation_id=correlation_id,
            idempotency_key=validated_key,
        )
        await session.commit()
        logger.info(
            "Modernization job paused | job_id=%s version=%d",
            job.id,
            job.version,
        )
        return JobLifecycleActionResponse(
            job_id=job.id,
            status=JobStatus(job.status),
            version=job.version,
            action="pause",
            updated_at=job.updated_at or datetime.now(UTC),
            message="Job paused successfully.",
        )
    except Exception:
        await session.rollback()
        raise


@router.post("/{job_id}/resume", response_model=JobLifecycleActionResponse)
async def resume_job(
    job_id: uuid.UUID,
    action_request: JobLifecycleActionRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", description="Unique request idempotency key")
    ] = None,
) -> JobLifecycleActionResponse:
    """Resume a paused modernization job."""
    try:
        correlation_id = request.headers.get("X-Correlation-ID")
        validated_key = _validate_idempotency_key(idempotency_key)
        service = JobService(session)
        job = await service.resume_job(
            principal=principal,
            job_id=job_id,
            expected_version=action_request.expected_version,
            reason=action_request.reason,
            correlation_id=correlation_id,
            idempotency_key=validated_key,
        )
        await session.commit()
        logger.info(
            "Modernization job resumed | job_id=%s version=%d",
            job.id,
            job.version,
        )
        return JobLifecycleActionResponse(
            job_id=job.id,
            status=JobStatus(job.status),
            version=job.version,
            action="resume",
            updated_at=job.updated_at or datetime.now(UTC),
            message="Job resumed successfully.",
        )
    except Exception:
        await session.rollback()
        raise


@router.post("/{job_id}/cancel", response_model=JobLifecycleActionResponse)
async def cancel_job(
    job_id: uuid.UUID,
    action_request: JobLifecycleActionRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", description="Unique request idempotency key")
    ] = None,
) -> JobLifecycleActionResponse:
    """Cooperatively and durably cancel a modernization job."""
    try:
        correlation_id = request.headers.get("X-Correlation-ID")
        validated_key = _validate_idempotency_key(idempotency_key)
        service = JobService(session)
        job = await service.cancel_job(
            principal=principal,
            job_id=job_id,
            expected_version=action_request.expected_version,
            reason=action_request.reason,
            correlation_id=correlation_id,
            idempotency_key=validated_key,
        )
        await session.commit()
        logger.info(
            "Modernization job cancelled | job_id=%s version=%d",
            job.id,
            job.version,
        )
        return JobLifecycleActionResponse(
            job_id=job.id,
            status=JobStatus(job.status),
            version=job.version,
            action="cancel",
            updated_at=job.updated_at or datetime.now(UTC),
            message="Job cancelled successfully.",
        )
    except Exception:
        await session.rollback()
        raise


@router.get("/{job_id}/artifacts", response_model=ArtifactListResponse)
async def list_job_artifacts(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    artifact_type: Annotated[str | None, Query()] = None,
) -> ArtifactListResponse:
    """List artifact metadata for an authorized job, optionally filtered by schema type."""
    try:
        service = AuthorizationService(session)
        artifacts = await service.list_job_artifacts(
            principal=principal,
            job_id=job_id,
            artifact_type=artifact_type,
        )
        items = [
            ArtifactDetailResponse(
                artifact_id=artifact.id,
                job_id=artifact.job_id,
                artifact_type=artifact.type,
                version=artifact.version,
                content_hash=artifact.content_hash,
                storage_ref=artifact.storage_ref,
                derived_from=artifact.derived_from or [],
                artifact_metadata=artifact.artifact_metadata or {},
                created_at=artifact.created_at or datetime.now(UTC),
            )
            for artifact in artifacts
        ]
        return ArtifactListResponse(items=items, total=len(items))
    except Exception:
        raise


@router.get("/{job_id}/artifacts/{artifact_type}", response_model=ArtifactDetailResponse)
async def get_job_artifact(
    job_id: uuid.UUID,
    artifact_type: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    version: Annotated[int | None, Query(ge=1)] = None,
) -> ArtifactDetailResponse:
    """Retrieve a specific artifact by job and schema type (latest or requested version)."""
    try:
        service = AuthorizationService(session)
        artifact = await service.get_job_artifact_by_type(
            principal=principal,
            job_id=job_id,
            artifact_type=artifact_type,
            version=version,
        )
        return ArtifactDetailResponse(
            artifact_id=artifact.id,
            job_id=artifact.job_id,
            artifact_type=artifact.type,
            version=artifact.version,
            content_hash=artifact.content_hash,
            storage_ref=artifact.storage_ref,
            derived_from=artifact.derived_from or [],
            artifact_metadata=artifact.artifact_metadata or {},
            created_at=artifact.created_at or datetime.now(UTC),
        )
    except Exception:
        raise


@router.get("/{job_id}/artifacts/{artifact_type}/content")
async def get_job_artifact_content(
    job_id: uuid.UUID,
    artifact_type: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    version: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    """Retrieve verified artifact content bytes after verifying job authorization."""
    try:
        service = AuthorizationService(session)
        stored_object = await service.get_job_artifact_content(
            principal=principal,
            job_id=job_id,
            artifact_type=artifact_type,
            version=version,
        )
        return Response(
            content=stored_object.data,
            media_type=stored_object.metadata.content_type,
            headers={
                "ETag": f'"{stored_object.metadata.content_hash}"',
                "Content-Length": str(stored_object.metadata.size_bytes),
            },
        )
    except Exception:
        raise


@router.get("/{job_id}/audit", response_model=AuditEventListResponse)
async def get_job_audit_trail(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> AuditEventListResponse:
    """Retrieve chronologically ordered audit events for an authorized job."""
    try:
        service = AuthorizationService(session)
        events, total = await service.list_job_audit_events(
            principal=principal,
            job_id=job_id,
            offset=offset,
            limit=limit,
        )
        items = [
            AuditEventResponse(
                event_id=event.id,
                job_id=event.job_id,
                actor=event.actor,
                actor_user_id=event.actor_user_id,
                action=event.action,
                correlation_id=event.correlation_id,
                payload=event.payload or {},
                event_time=event.event_time or datetime.now(UTC),
                event_version=event.event_version,
            )
            for event in events
        ]
        return AuditEventListResponse(
            items=items,
            pagination=PaginationMetadata(offset=offset, limit=limit, total=total),
        )
    except Exception:
        raise


@router.get("/{job_id}/gates", response_model=GateListResponse)
async def list_job_gates(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    state: Annotated[str | None, Query()] = None,
) -> GateListResponse:
    """List approval gates for an authorized job."""
    try:
        from modernization_platform.api.v1.endpoints.gates import map_gate_detail
        from modernization_platform.services.gates import GateService

        service = GateService(session)
        gates = await service.list_job_gates(
            principal=principal,
            job_id=job_id,
            state=state,
        )
        items = [map_gate_detail(gate) for gate in gates]
        return GateListResponse(items=items, total=len(items))
    except Exception:
        raise


@router.get("/{job_id}/gates/{gate_id}", response_model=GateDetailResponse)
async def get_job_gate(
    job_id: uuid.UUID,
    gate_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDetailResponse:
    """Retrieve full details of a specific gate for an authorized job."""
    try:
        from modernization_platform.api.v1.endpoints.gates import map_gate_detail
        from modernization_platform.services.gates import GateService

        service = GateService(session)
        gate = await service.get_gate(
            principal=principal,
            job_id=job_id,
            gate_id=gate_id,
        )
        return map_gate_detail(gate)
    except Exception:
        raise


@router.post(
    "/{job_id}/source/ingest",
    response_model=SourceProvenanceResponse,
    status_code=status.HTTP_200_OK,
)
async def ingest_job_source(
    job_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    body: SourceIngestRequest | None = None,
) -> SourceProvenanceResponse:
    """Ingest remote source repository for an authorized job and record reproducible provenance."""
    try:
        correlation_id = request.headers.get("X-Correlation-ID")
        credentials: GitCredentials | None = None
        ref_override: str | None = None

        if body is not None:
            ref_override = str(body.ref_override) if body.ref_override else None
            if body.git_token or body.git_password:
                credentials = GitCredentials(
                    username=str(body.git_username) if body.git_username else None,
                    password=body.git_password,
                    token=body.git_token,
                )

        service = SourceIngestionService(session)
        provenance = await service.ingest_source(
            principal=principal,
            job_id=job_id,
            credentials=credentials,
            ref_override=ref_override,
            correlation_id=correlation_id,
        )

        return SourceProvenanceResponse(
            job_id=provenance.job_id,
            repository_url=provenance.repository_url,
            provider=provenance.provider,
            requested_ref=provenance.requested_ref,
            resolved_commit_sha=provenance.resolved_commit_sha,
            branch=provenance.branch,
            tree_hash=provenance.tree_hash,
            commit_author=provenance.commit_author,
            commit_author_email=provenance.commit_author_email,
            commit_timestamp=provenance.commit_timestamp,
            commit_message=provenance.commit_message,
            file_count=provenance.repository_metadata.file_count,
            size_bytes=provenance.repository_metadata.size_bytes,
            provenance_hash=provenance.provenance_hash,
            ingestion_status=provenance.ingestion_status,
            ingested_at=provenance.ingestion_timestamp,
            repository_metadata=provenance.repository_metadata.model_dump(mode="json"),
        )
    except Exception:
        raise


@router.get(
    "/{job_id}/source/provenance",
    response_model=SourceProvenanceResponse,
    status_code=status.HTTP_200_OK,
)
async def get_job_source_provenance(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SourceProvenanceResponse:
    """Retrieve immutable source provenance record for an authorized job."""
    try:
        service = SourceIngestionService(session)
        record = await service.get_provenance(principal=principal, job_id=job_id)
        if record is None:
            raise NotFoundException(
                message=f"Source provenance for job '{job_id}' has not been recorded.",
                code="SOURCE_PROVENANCE_NOT_FOUND",
            )

        return SourceProvenanceResponse(
            job_id=record.job_id,
            repository_url=record.repository_url,
            provider=record.provider,
            requested_ref=record.requested_ref,
            resolved_commit_sha=record.resolved_commit_sha,
            branch=record.branch,
            tree_hash=record.tree_hash,
            commit_author=record.commit_author,
            commit_author_email=record.commit_author_email,
            commit_timestamp=record.commit_timestamp,
            commit_message=record.commit_message,
            file_count=record.file_count,
            size_bytes=record.size_bytes,
            provenance_hash=record.provenance_hash,
            ingestion_status=record.ingestion_status,
            ingested_at=record.ingested_at,
            repository_metadata=record.repository_metadata or {},
        )
    except Exception:
        raise


@router.post(
    "/{job_id}/source/branches",
    response_model=ModuleBranchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_module_branch(
    job_id: uuid.UUID,
    body: ModuleBranchRequest,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModuleBranchResponse:
    """Create an isolated module branch adhering to job/{job_id}/{module} naming convention."""
    try:
        service = SourceIngestionService(session)
        branch_name = await service.create_module_workspace(
            principal=principal,
            job_id=job_id,
            module=str(body.module),
        )
        return ModuleBranchResponse(
            job_id=job_id,
            module=str(body.module),
            branch_name=branch_name,
            created_at=datetime.now(UTC),
        )
    except Exception:
        raise


@router.delete(
    "/{job_id}/source/workspace",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cleanup_job_workspace(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Safely delete isolated working copy files for a job."""
    try:
        service = SourceIngestionService(session)
        await service.cleanup_job_workspace(principal=principal, job_id=job_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception:
        raise


__all__ = ["router"]
