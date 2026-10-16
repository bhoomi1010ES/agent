"""Artifact REST API endpoints for metadata, streaming content, lineage, and verification."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.session import get_db_session
from modernization_platform.schemas.artifacts import (
    ArtifactDeleteResponse,
    ArtifactDetailResponse,
    ArtifactIntegrityVerificationResponse,
    ArtifactLineageResponse,
)
from modernization_platform.security.dependencies import CurrentPrincipal
from modernization_platform.services.authorization import AuthorizationService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{artifact_id}", response_model=ArtifactDetailResponse)
async def get_artifact_detail(
    artifact_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ArtifactDetailResponse:
    """Retrieve authoritative metadata for a specific artifact within authorized scope."""
    try:
        service = AuthorizationService(session)
        artifact = await service.get_artifact(principal=principal, artifact_id=artifact_id)
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
            status=artifact.status or "available",
            size_bytes=artifact.size_bytes,
            content_type=artifact.content_type or "application/json",
        )
    except Exception:
        raise


@router.get("/{artifact_id}/content")
async def get_artifact_content_stream(
    artifact_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    """Stream verified artifact content bytes with on-the-fly hash integrity verification."""
    try:
        service = AuthorizationService(session)
        artifact, meta, stream = await service.stream_artifact_content(
            principal=principal,
            artifact_id=artifact_id,
        )
        headers = {
            "ETag": f'"{meta.content_hash}"',
            "Content-Disposition": f'attachment; filename="{artifact.type}_v{artifact.version}.bin"',
        }
        if meta.size_bytes is not None:
            headers["Content-Length"] = str(meta.size_bytes)

        return StreamingResponse(
            stream,
            media_type=meta.content_type or "application/octet-stream",
            headers=headers,
        )
    except Exception:
        raise


@log_errors
def _to_detail(a: Any) -> ArtifactDetailResponse:
    """Format an Artifact ORM model into an ArtifactDetailResponse schema."""
    try:
        return ArtifactDetailResponse(
            artifact_id=a.id,
            job_id=a.job_id,
            artifact_type=a.type,
            version=a.version,
            content_hash=a.content_hash,
            storage_ref=a.storage_ref,
            derived_from=a.derived_from or [],
            artifact_metadata=a.artifact_metadata or {},
            created_at=a.created_at or datetime.now(UTC),
            status=a.status or "available",
            size_bytes=a.size_bytes,
            content_type=a.content_type or "application/json",
        )
    except Exception:
        raise


@router.get("/{artifact_id}/lineage", response_model=ArtifactLineageResponse)
async def get_artifact_lineage_graph(
    artifact_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ArtifactLineageResponse:
    """Retrieve direct upstream parents and downstream children lineage graph."""
    try:
        service = AuthorizationService(session)
        artifact, parents, children = await service.get_artifact_lineage(
            principal=principal,
            artifact_id=artifact_id,
        )

        return ArtifactLineageResponse(
            artifact_id=artifact.id,
            job_id=artifact.job_id,
            parents=[_to_detail(p) for p in parents],
            children=[_to_detail(c) for c in children],
        )
    except Exception:
        raise


@router.post("/{artifact_id}/verify", response_model=ArtifactIntegrityVerificationResponse)
async def verify_artifact_integrity_endpoint(
    artifact_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ArtifactIntegrityVerificationResponse:
    """Perform explicit end-to-end cryptographic and storage presence integrity check."""
    try:
        correlation_id = request.headers.get("X-Correlation-ID")
        service = AuthorizationService(session)
        artifact, verified = await service.verify_artifact_integrity(
            principal=principal,
            artifact_id=artifact_id,
            correlation_id=correlation_id,
        )
        return ArtifactIntegrityVerificationResponse(
            artifact_id=artifact.id,
            job_id=artifact.job_id,
            verified=verified,
            content_hash=artifact.content_hash,
            size_bytes=artifact.size_bytes,
            verified_at=datetime.now(UTC),
        )
    except Exception:
        raise


@router.delete("/{artifact_id}", response_model=ArtifactDeleteResponse)
async def delete_artifact_endpoint(
    artifact_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ArtifactDeleteResponse:
    """Safely delete an artifact subject to active job protection and lineage retention rules."""
    try:
        correlation_id = request.headers.get("X-Correlation-ID")
        service = AuthorizationService(session)
        artifact = await service.get_artifact(principal=principal, artifact_id=artifact_id)
        job_id = artifact.job_id
        await service.delete_artifact(
            principal=principal,
            artifact_id=artifact_id,
            correlation_id=correlation_id,
        )
        await session.commit()
        return ArtifactDeleteResponse(
            artifact_id=artifact_id,
            job_id=job_id,
            deleted=True,
            message="Artifact and storage object safely deleted under retention policy.",
        )
    except Exception:
        await session.rollback()
        raise


__all__ = ["router"]
