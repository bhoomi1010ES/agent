"""REST API endpoints for human approval gates, decisions, and resume operations."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.db.session import get_db_session
from modernization_platform.domain.gates.states import GateDecisionType
from modernization_platform.schemas.gates import (
    GateApproveRequest,
    GateCreateRequest,
    GateDecisionDetailResponse,
    GateDecisionRequest,
    GateDetailResponse,
    GateRejectRequest,
    GateResumeRequest,
)
from modernization_platform.security.dependencies import CurrentPrincipal
from modernization_platform.services.gates import GateService

logger = logging.getLogger(__name__)

router = APIRouter()


@log_errors
def map_gate_decision(dec: GateDecision) -> GateDecisionDetailResponse:
    """Map a GateDecision ORM instance to transport schema."""
    try:
        return GateDecisionDetailResponse(
            id=dec.id,
            gate_id=dec.gate_id,
            job_id=dec.job_id,
            gate_type=dec.gate_type,
            actor=dec.actor,
            actor_user_id=dec.actor_user_id,
            approver_role=dec.approver_role,
            decision=dec.decision,
            feedback=dec.feedback,
            waivers=dec.waivers,
            artifact_version_refs=dec.artifact_version_refs,
            artifact_diff_ref=dec.artifact_diff_ref,
            decided_at=dec.decided_at,
        )
    except Exception as exc:
        logger.exception("map_gate_decision failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
def map_gate_detail(gate: Gate) -> GateDetailResponse:
    """Map a Gate ORM instance with attached decisions to transport schema."""
    try:
        return GateDetailResponse(
            gate_id=gate.id,
            job_id=gate.job_id,
            gate_type=gate.gate_type,
            state=gate.state,
            requested_at=gate.requested_at or datetime.now(UTC),
            timeout_at=gate.timeout_at,
            workflow_thread_id=gate.workflow_thread_id,
            artifact_versions_shown=gate.artifact_versions_shown or {},
            artifact_diff_ref=gate.artifact_diff_ref,
            needs_human_flags=gate.needs_human_flags or [],
            budget_used_cents=gate.budget_used_cents or 0.0,
            resolved_at=gate.resolved_at,
            resolved_by=gate.resolved_by,
            resolved_by_user_id=gate.resolved_by_user_id,
            updated_at=gate.updated_at,
            decisions=[map_gate_decision(d) for d in (gate.decisions or [])],
        )
    except Exception as exc:
        logger.exception("map_gate_detail failed | %s: %s", type(exc).__name__, exc)
        raise


# --------------------------------------------------------------------------
# Direct Gate Endpoints: /gates/{gate_id}...
# --------------------------------------------------------------------------


@router.get("/gates/{gate_id}", response_model=GateDetailResponse)
@log_errors
async def get_gate(
    gate_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDetailResponse:
    """Retrieve full details of an approval gate by ID."""
    try:
        service = GateService(session)
        gate = await service.get_gate(principal=principal, gate_id=gate_id)
        return map_gate_detail(gate)
    except Exception:
        raise


@router.get("/gates/{gate_id}/decisions", response_model=list[GateDecisionDetailResponse])
@log_errors
async def list_gate_decisions(
    gate_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[GateDecisionDetailResponse]:
    """Retrieve immutable audit decision history for a gate."""
    try:
        service = GateService(session)
        decisions = await service.list_gate_decisions(principal=principal, gate_id=gate_id)
        return [map_gate_decision(d) for d in decisions]
    except Exception:
        raise


@router.post(
    "/gates/{gate_id}/approve",
    response_model=GateDecisionDetailResponse,
    status_code=status.HTTP_200_OK,
)
@log_errors
async def approve_gate(
    gate_id: uuid.UUID,
    body: GateApproveRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDecisionDetailResponse:
    """Approve a pending gate with exact artifact-version binding and server-derived identity."""
    try:
        service = GateService(session)
        decision = await service.decide_gate(
            principal=principal,
            gate_id=gate_id,
            decision=GateDecisionType.APPROVED.value,
            reason=body.reason,
            artifact_versions=body.artifact_versions,
            artifact_diff_ref=body.artifact_diff_ref,
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
        await session.commit()
        return map_gate_decision(decision)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/gates/{gate_id}/reject",
    response_model=GateDecisionDetailResponse,
    status_code=status.HTTP_200_OK,
)
@log_errors
async def reject_gate(
    gate_id: uuid.UUID,
    body: GateRejectRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDecisionDetailResponse:
    """Reject a pending gate with mandatory feedback and return to designated workflow stage."""
    try:
        service = GateService(session)
        decision = await service.decide_gate(
            principal=principal,
            gate_id=gate_id,
            decision=GateDecisionType.REJECTED.value,
            reason=body.reason,
            artifact_versions=body.artifact_versions,
            artifact_diff_ref=body.artifact_diff_ref,
            return_to_stage=body.return_to_stage,
            rejection_target=body.rejection_target,
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
        await session.commit()
        return map_gate_decision(decision)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/gates/{gate_id}/resume",
    response_model=GateDetailResponse,
    status_code=status.HTTP_200_OK,
)
@log_errors
async def resume_gate(
    gate_id: uuid.UUID,
    body: GateResumeRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDetailResponse:
    """Resume a paused or timed out gate back to pending state."""
    try:
        service = GateService(session)
        gate = await service.resume_gate(
            principal=principal,
            gate_id=gate_id,
            reason=body.reason,
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
        await session.commit()
        # Reload gate with decisions
        gate.decisions = await service.list_gate_decisions(principal=principal, gate_id=gate_id)
        return map_gate_detail(gate)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/gates/{gate_id}/decide",
    response_model=GateDecisionDetailResponse,
    status_code=status.HTTP_200_OK,
)
@log_errors
async def decide_gate_generic(
    gate_id: uuid.UUID,
    body: GateDecisionRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDecisionDetailResponse:
    """Generic decision endpoint supporting approve, reject, and waivers."""
    try:
        service = GateService(session)
        effective_reason = body.reason or body.feedback
        waivers_payload = (
            [w.model_dump(mode="json") for w in body.waivers] if body.waivers else None
        )
        decision = await service.decide_gate(
            principal=principal,
            gate_id=gate_id,
            decision=body.decision.value,
            reason=effective_reason,
            artifact_versions=body.artifact_versions,
            artifact_diff_ref=body.artifact_diff_ref,
            waivers=waivers_payload,
            return_to_stage=body.return_to_stage,
            rejection_target=body.rejection_target,
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
        await session.commit()
        return map_gate_decision(decision)
    except Exception:
        await session.rollback()
        raise


# --------------------------------------------------------------------------
# Job-Scoped Gate Endpoints: /jobs/{job_id}/gates...
# --------------------------------------------------------------------------


@router.post(
    "/jobs/{job_id}/gates",
    response_model=GateDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
@log_errors
async def create_job_gate(
    job_id: uuid.UUID,
    body: GateCreateRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDetailResponse:
    """Create a new human approval gate for an authorized job."""
    try:
        service = GateService(session)
        gate = await service.create_gate(
            principal=principal,
            job_id=job_id,
            gate_type=body.gate_type,
            timeout_seconds=body.timeout_seconds,
            artifact_versions_shown=body.artifact_versions_shown,
            artifact_diff_ref=body.artifact_diff_ref,
            needs_human_flags=body.needs_human_flags,
            budget_used_cents=body.budget_used_cents,
            workflow_thread_id=body.workflow_thread_id,
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
        await session.commit()
        gate.decisions = []
        return map_gate_detail(gate)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/jobs/{job_id}/gates/{gate_id}/approve",
    response_model=GateDecisionDetailResponse,
    status_code=status.HTTP_200_OK,
)
@log_errors
async def approve_job_gate(
    job_id: uuid.UUID,
    gate_id: uuid.UUID,
    body: GateApproveRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDecisionDetailResponse:
    """Approve a gate under an authorized job scope."""
    try:
        service = GateService(session)
        decision = await service.decide_gate(
            principal=principal,
            gate_id=gate_id,
            job_id=job_id,
            decision=GateDecisionType.APPROVED.value,
            reason=body.reason,
            artifact_versions=body.artifact_versions,
            artifact_diff_ref=body.artifact_diff_ref,
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
        await session.commit()
        return map_gate_decision(decision)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/jobs/{job_id}/gates/{gate_id}/reject",
    response_model=GateDecisionDetailResponse,
    status_code=status.HTTP_200_OK,
)
@log_errors
async def reject_job_gate(
    job_id: uuid.UUID,
    gate_id: uuid.UUID,
    body: GateRejectRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDecisionDetailResponse:
    """Reject a gate under an authorized job scope."""
    try:
        service = GateService(session)
        decision = await service.decide_gate(
            principal=principal,
            gate_id=gate_id,
            job_id=job_id,
            decision=GateDecisionType.REJECTED.value,
            reason=body.reason,
            artifact_versions=body.artifact_versions,
            artifact_diff_ref=body.artifact_diff_ref,
            return_to_stage=body.return_to_stage,
            rejection_target=body.rejection_target,
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
        await session.commit()
        return map_gate_decision(decision)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/jobs/{job_id}/gates/{gate_id}/resume",
    response_model=GateDetailResponse,
    status_code=status.HTTP_200_OK,
)
@log_errors
async def resume_job_gate(
    job_id: uuid.UUID,
    gate_id: uuid.UUID,
    body: GateResumeRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GateDetailResponse:
    """Resume a paused gate under an authorized job scope."""
    try:
        service = GateService(session)
        gate = await service.resume_gate(
            principal=principal,
            gate_id=gate_id,
            job_id=job_id,
            reason=body.reason,
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
        await session.commit()
        gate.decisions = await service.list_gate_decisions(
            principal=principal, gate_id=gate_id, job_id=job_id
        )
        return map_gate_detail(gate)
    except Exception:
        await session.rollback()
        raise


__all__ = ["router"]
