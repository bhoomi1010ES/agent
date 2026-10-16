"""Job lifecycle, artifact retrieval, and audit trail REST API endpoints."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.exceptions import UnprocessableEntityException
from modernization_platform.db.session import get_db_session
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
    JobListResponse,
    JobSummaryResponse,
    PaginationMetadata,
)
from modernization_platform.schemas.status import JobStatus
from modernization_platform.security.dependencies import CurrentPrincipal
from modernization_platform.services.authorization import AuthorizationService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_request: JobCreateRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JobCreateResponse:
    """Create a modernization job, initialize tenant membership, and log an audit event."""
    try:
        correlation_id = request.headers.get("X-Correlation-ID")
        service = AuthorizationService(session)
        job = await service.create_job(
            principal=principal,
            source_repository=str(job_request.source_repository),
            source_revision=str(job_request.source_revision),
            target_stack_spec=job_request.target_stack.model_dump(mode="json"),
            budget=job_request.budget.model_dump(mode="json"),
            correlation_id=correlation_id,
        )
        await session.commit()
        logger.info(
            "Modernization job created | job_id=%s tenant_id=%s owner_user_id=%s",
            job.id,
            principal.tenant_id,
            principal.user_id,
        )
        return JobCreateResponse(
            job_id=job.id,
            status=JobStatus(job.status),
            created_at=job.created_at or datetime.now(UTC),
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
        service = AuthorizationService(session)
        jobs, total = await service.list_jobs(
            principal=principal,
            offset=offset,
            limit=limit,
            status=status.value if status else None,
        )
        items = [
            JobSummaryResponse(
                job_id=job.id,
                tenant_id=job.tenant_id or principal.tenant_id,
                owner_user_id=job.owner_user_id or principal.user_id,
                status=JobStatus(job.status),
                source_ref=job.source_ref,
                target_stack_spec=job.target_stack_spec,
                budget=job.budget,
                created_at=job.created_at or datetime.now(UTC),
                updated_at=job.updated_at or datetime.now(UTC),
                finished_at=job.finished_at,
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
        service = AuthorizationService(session)
        job = await service.get_job(principal=principal, job_id=job_id)
        if job.tenant_id is None or job.owner_user_id is None:
            raise UnprocessableEntityException("Job record is missing required ownership scope")
        return JobDetailResponse(
            job_id=job.id,
            tenant_id=job.tenant_id,
            owner_user_id=job.owner_user_id,
            status=JobStatus(job.status),
            source_ref=job.source_ref,
            target_stack_spec=job.target_stack_spec,
            budget=job.budget,
            created_at=job.created_at or datetime.now(UTC),
            updated_at=job.updated_at or datetime.now(UTC),
            finished_at=job.finished_at,
        )
    except Exception:
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
        service = AuthorizationService(session)
        gates = await service.list_job_gates(
            principal=principal,
            job_id=job_id,
            state=state,
        )
        items = [
            GateDetailResponse(
                gate_id=gate.id,
                job_id=gate.job_id,
                gate_type=gate.gate_type,
                state=gate.state,
                requested_at=gate.requested_at or datetime.now(UTC),
                artifact_versions_shown=gate.artifact_versions_shown or {},
                needs_human_flags=gate.needs_human_flags or [],
                budget_used_cents=gate.budget_used_cents or 0.0,
                resolved_at=gate.resolved_at,
            )
            for gate in gates
        ]
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
        service = AuthorizationService(session)
        gate = await service.get_job_gate(
            principal=principal,
            job_id=job_id,
            gate_id=gate_id,
        )
        return GateDetailResponse(
            gate_id=gate.id,
            job_id=gate.job_id,
            gate_type=gate.gate_type,
            state=gate.state,
            requested_at=gate.requested_at or datetime.now(UTC),
            artifact_versions_shown=gate.artifact_versions_shown or {},
            needs_human_flags=gate.needs_human_flags or [],
            budget_used_cents=gate.budget_used_cents or 0.0,
            resolved_at=gate.resolved_at,
        )
    except Exception:
        raise


__all__ = ["router"]
