"""Minimal authenticated resource endpoints proving the security boundaries."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.session import get_db_session
from modernization_platform.schemas.gates import GateDecisionRequest, GateDecisionResponse
from modernization_platform.schemas.security import (
    SecuredArtifactResponse,
    SecuredJobResponse,
)
from modernization_platform.schemas.status import JobStatus
from modernization_platform.security.dependencies import CurrentPrincipal
from modernization_platform.services.authorization import AuthorizationService

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=SecuredJobResponse)
async def get_job(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SecuredJobResponse:
    """Return a job only when tenant and job membership authorize access."""
    try:
        job = await AuthorizationService(session).get_job(principal, job_id)
        if job.tenant_id is None or job.owner_user_id is None:
            raise RuntimeError("Secured job is missing its authorization scope")
        return SecuredJobResponse(
            job_id=job.id,
            tenant_id=job.tenant_id,
            owner_user_id=job.owner_user_id,
            status=JobStatus(job.status),
        )
    except Exception:
        raise


@router.get("/artifacts/{artifact_id}", response_model=SecuredArtifactResponse)
async def get_artifact(
    artifact_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SecuredArtifactResponse:
    """Return artifact metadata only through the authorized parent job."""
    try:
        artifact = await AuthorizationService(session).get_artifact(principal, artifact_id)
        return SecuredArtifactResponse(
            artifact_id=artifact.id,
            job_id=artifact.job_id,
            artifact_type=artifact.type,
            version=artifact.version,
            content_hash=artifact.content_hash,
        )
    except Exception:
        raise


@router.post(
    "/jobs/{job_id}/gates/{gate_id}/decisions",
    response_model=GateDecisionResponse,
)
async def decide_gate(
    job_id: uuid.UUID,
    gate_id: uuid.UUID,
    decision_request: GateDecisionRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDecisionResponse:
    """Record a decision whose actor comes only from the authenticated principal."""
    try:
        decision = await AuthorizationService(session).decide_gate(
            principal=principal,
            job_id=job_id,
            gate_id=gate_id,
            decision=decision_request.decision.value,
            feedback=decision_request.feedback,
            waivers=[item.model_dump(mode="json") for item in decision_request.waivers],
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
        await session.commit()
        return GateDecisionResponse(
            gate_id=gate_id,
            decision_id=decision.id,
            decision=decision_request.decision,
            decided_at=decision.decided_at,
        )
    except Exception:
        await session.rollback()
        raise


__all__ = ["router"]
